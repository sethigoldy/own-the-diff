"""Frozen Git evidence. All writes go to disposable indexes and object stores."""

import fnmatch
import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import zlib
from datetime import datetime, timezone

_DIFF = [
    "--no-ext-diff",
    "--no-textconv",
    "--no-color",
    "--no-relative",
    "--diff-algorithm=myers",
    "--no-indent-heuristic",
    "--unified=3",
    "--ignore-submodules=none",
    "--src-prefix=a/",
    "--dst-prefix=b/",
]
_DETECT = ["--find-renames=50%", "--find-copies=50%", "--find-copies-harder"]
_ZERO = re.compile(r"^0+$")
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.M)


def _identity(*parts):
    return hashlib.sha256(
        "\0".join(str(p) for p in parts).encode("utf-8", "surrogateescape")
    ).hexdigest()


def _environment():
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_OPTIONAL_LOCKS="0",
        GIT_TERMINAL_PROMPT="0",
        LC_ALL="C",
    )
    return env


class _Git:
    def __init__(self, root, env):
        self.root, self.env = str(root), env
        self.object_format = "sha1"
        self.filemode = True
        self.written_blobs = set()

    def store_blob(self, data, indexed_oid=None):
        header = ("blob %d\0" % len(data)).encode("ascii")
        digest = hashlib.new(self.object_format)
        digest.update(header)
        digest.update(data)
        oid = digest.hexdigest()
        if oid == indexed_oid or oid in self.written_blobs:
            return oid
        # Raw loose objects bypass attributes/filters; only scratch storage is writable.
        path = Path(self.env["GIT_OBJECT_DIRECTORY"]) / oid[:2] / oid[2:]
        path.parent.mkdir(exist_ok=True)
        if not path.exists():
            compressor = zlib.compressobj()
            with path.open("xb") as stream:
                stream.write(compressor.compress(header))
                stream.write(compressor.compress(data))
                stream.write(compressor.flush())
        self.written_blobs.add(oid)
        return oid

    def run(self, *args, data=None):
        command = [
            "git",
            "-c",
            "core.hooksPath=" + os.devnull,
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.untrackedCache=false",
            "-c",
            "core.splitIndex=false",
            "-c",
            "core.attributesFile=" + os.devnull,
            "-c",
            "diff.external=",
            "-c",
            "core.quotePath=true",
            "-C",
            self.root,
        ] + list(args)
        try:
            result = subprocess.run(
                command,
                input=data,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self.env,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError(
                "Cannot capture repository %s: %s. Check Git and repository access."
                % (self.root, exc)
            ) from exc
        if result.returncode:
            detail = result.stderr.decode("utf-8", "replace").strip()
            raise ValueError(
                "Git capture failed in %s (%s): %s" % (self.root, args[0], detail)
            )
        return result.stdout


def _decode(data):
    return os.fsdecode(data)


def _text(data):
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _entries(git, tree):
    entries = {}
    for record in git.run("ls-tree", "-r", "-z", "--full-tree", tree).split(b"\0"):
        if record:
            header, path = record.split(b"\t", 1)
            mode, kind, oid = header.decode("ascii").split()
            entries[_decode(path)] = (mode, oid)
    return entries


def _safe_path(root, name):
    path = Path(root) / name
    if name.startswith("/") or ".." in Path(name).parts or ".git" in Path(name).parts:
        raise ValueError("Unsafe repository path %r; capture stopped." % name)
    if not path.parent.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError(
            "Path %r traverses a symlink outside the repository; capture stopped."
            % name
        )
    return path


def _working_tree(git, root, include_untracked):
    records = git.run("ls-files", "--stage", "-z").split(b"\0")
    tracked = {}
    for record in records:
        if not record:
            continue
        header, name = record.split(b"\t", 1)
        mode, oid, stage = header.decode("ascii").split()
        if stage != "0":
            raise ValueError(
                "Repository has an unresolved merge at %r. Resolve and stage it before capture."
                % _decode(name)
            )
        tracked[_decode(name)] = (mode, oid)
    sparse = git.run("ls-files", "-v", "-z").split(b"\0")
    if any(record.startswith(b"S ") for record in sparse):
        raise ValueError(
            "Sparse checkout is unsupported. Materialize all tracked paths before capture."
        )
    names = set(tracked)
    if include_untracked:
        names.update(
            _decode(p)
            for p in git.run("ls-files", "--others", "--exclude-standard", "-z").split(
                b"\0"
            )
            if p
        )
    result = {}
    for name in sorted(names):
        path = _safe_path(root, name)
        previous_mode, previous_oid = tracked.get(name, ("100644", ""))
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if previous_mode == "160000":
            if not stat.S_ISDIR(info.st_mode):
                raise ValueError(
                    "Submodule %r is not a directory. Restore or stage its replacement."
                    % name
                )
            # Nested edits are outside this repository's tree; only the checked-out commit is included.
            if (path / ".git").exists():
                oid = (
                    _Git(path, _environment())
                    .run("rev-parse", "--verify", "HEAD^{commit}")
                    .strip()
                    .decode("ascii")
                )
            else:
                oid = previous_oid
            result[name] = ("160000", oid)
            continue
        if stat.S_ISLNK(info.st_mode):
            mode, data = "120000", os.fsencode(os.readlink(path))
        elif stat.S_ISREG(info.st_mode):
            if git.filemode:
                mode = "100755" if info.st_mode & 0o111 else "100644"
            else:
                mode = (
                    previous_mode if previous_mode in ("100644", "100755") else "100644"
                )
            data = path.read_bytes()
        else:
            raise ValueError(
                "Unsupported tracked path %r. Only regular files, symlinks and submodules can be captured."
                % name
            )
        oid = git.store_blob(data, previous_oid)
        result[name] = (mode, oid)
    git.run("read-tree", "--empty")
    data = b"".join(
        mode.encode() + b" " + oid.encode() + b"\t" + os.fsencode(name) + b"\0"
        for name, (mode, oid) in sorted(result.items())
    )
    if data:
        git.run("update-index", "-z", "--index-info", data=data)
    return git.run("write-tree").strip().decode("ascii")


def _manifest(git, base, target):
    raw = git.run(
        "diff", *_DIFF, *_DETECT, "--raw", "--no-abbrev", "-z", base, target, "--"
    )
    pieces, result, index = raw.split(b"\0"), [], 0
    while index < len(pieces) and pieces[index]:
        header = pieces[index].decode("ascii").split()
        index += 1
        old_mode, new_mode, old_oid, new_oid, status = header
        old_mode = old_mode[1:]
        first = _decode(pieces[index])
        index += 1
        if status[0] in "RC":
            second = _decode(pieces[index])
            index += 1
            old_path, path = first, second
        else:
            old_path = first if status[0] != "A" else None
            path = first
        result.append(
            dict(
                path=path,
                old_path=old_path,
                status_code=status,
                old_mode=old_mode,
                new_mode=new_mode,
                old_oid=old_oid,
                new_oid=new_oid,
            )
        )
    # A separately encoded Git manifest must agree on every path and transition.
    names = git.run(
        "diff", *_DIFF, *_DETECT, "--name-status", "-z", base, target, "--"
    ).split(b"\0")
    independent, i = [], 0
    while i < len(names) and names[i]:
        status = names[i].decode("ascii")
        first = _decode(names[i + 1])
        i += 2
        second = _decode(names[i]) if status[0] in "RC" else first
        if status[0] in "RC":
            i += 1
        independent.append((status, first if status[0] != "A" else None, second))
    if independent != [(f["status_code"], f["old_path"], f["path"]) for f in result]:
        raise ValueError(
            "Independent Git manifests disagree. Retry capture; no snapshot was published."
        )
    return result


def _blob(git, oid, mode):
    return (
        None
        if mode in ("000000", "160000") or _ZERO.match(oid)
        else git.run("cat-file", "blob", oid)
    )


def _capture(config, destination=None, expected=None):
    alias = config.get("alias", "")
    if not isinstance(alias, str) or not alias.strip():
        raise ValueError("Each repository needs a non-empty alias.")
    root = Path(config.get("path", "")).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(
            "Repository %s is missing: %s. Reconnect its folder." % (alias, root)
        )
    env = _environment()
    git = _Git(root, env)
    actual_root = Path(
        _decode(git.run("rev-parse", "--show-toplevel").strip())
    ).resolve()
    if root != actual_root:
        raise ValueError(
            "Select the repository root %s, rather than %s." % (actual_root, root)
        )
    git.object_format = (
        git.run("rev-parse", "--show-object-format").strip().decode("ascii")
    )
    if git.object_format not in ("sha1", "sha256"):
        raise ValueError("Unsupported Git object format %s." % git.object_format)
    git.filemode = (
        git.run(
            "config", "--type=bool", "--default=true", "--get", "core.filemode"
        ).strip()
        == b"true"
    )
    base_ref, target_ref = config.get("base", "HEAD"), config.get("target", "WORKTREE")
    if (
        not isinstance(base_ref, str)
        or not isinstance(target_ref, str)
        or base_ref.startswith("-")
        or target_ref.startswith("-")
    ):
        raise ValueError(
            "Base and target must name commits or refs; use WORKTREE for on-disk files."
        )
    base = (
        git.run("rev-parse", "--verify", "--end-of-options", base_ref + "^{commit}")
        .strip()
        .decode("ascii")
    )
    object_path = Path(_decode(git.run("rev-parse", "--git-path", "objects").strip()))
    if not object_path.is_absolute():
        object_path = root / object_path
    index_path = Path(_decode(git.run("rev-parse", "--git-path", "index").strip()))
    if not index_path.is_absolute():
        index_path = root / index_path
    with tempfile.TemporaryDirectory(prefix="cor-capture-") as scratch:
        objects, index = Path(scratch) / "objects", Path(scratch) / "index"
        objects.mkdir()
        env.update(
            GIT_OBJECT_DIRECTORY=str(objects),
            GIT_ALTERNATE_OBJECT_DIRECTORIES=str(object_path.resolve()),
            GIT_INDEX_FILE=str(index),
        )
        working = target_ref == "WORKTREE"
        if working:
            original_index = index_path.read_bytes() if index_path.exists() else None
            if original_index is not None:
                index.write_bytes(original_index)
            first = _working_tree(
                git, root, bool(config.get("include_untracked", False))
            )
            # Re-read the actual index and all selected content, not timestamps alone.
            if index_path.exists():
                index.write_bytes(index_path.read_bytes())
            else:
                index.unlink(missing_ok=True)
            target = _working_tree(
                git, root, bool(config.get("include_untracked", False))
            )
            current_index = index_path.read_bytes() if index_path.exists() else None
            if first != target or original_index != current_index:
                raise ValueError(
                    "Repository %s changed during capture. Stop edits and retry."
                    % alias
                )
            target_commit = None
        else:
            target_commit = (
                git.run(
                    "rev-parse",
                    "--verify",
                    "--end-of-options",
                    target_ref + "^{commit}",
                )
                .strip()
                .decode("ascii")
            )
            target = (
                git.run("rev-parse", target_commit + "^{tree}").strip().decode("ascii")
            )
        files, hunk_count = [], 0
        manifest = _manifest(git, base, target)
        canonical = git.run(
            "diff", *_DIFF, *_DETECT, "--full-index", "--patch", base, target, "--"
        ).decode("utf-8", "replace")
        sections = re.split(r"(?m)(?=^diff --git )", canonical)
        sections = [section for section in sections if section]
        if len(sections) != len(manifest):
            raise ValueError(
                "Canonical Git patch file count disagrees with manifest. Retry capture."
            )
        empty = git.store_blob(b"")
        for item, canonical_file in zip(manifest, sections):
            code = item.pop("status_code")
            status = {
                "A": "added",
                "D": "deleted",
                "M": "modified",
                "R": "renamed",
                "C": "copied",
                "T": "type changed",
            }.get(code[0])
            if status is None:
                raise ValueError(
                    "Unsupported Git status %s for %r; resolve repository state and retry."
                    % (code, item["path"])
                )
            old_data = _blob(git, item["old_oid"], item["old_mode"])
            new_data = _blob(git, item["new_oid"], item["new_mode"])
            fid = _identity(alias, item["old_path"], item["path"])
            file = dict(
                item,
                id=fid,
                repo=alias,
                status=status,
                git_status=code,
                patch=canonical_file,
                old_text=_text(old_data) if old_data is not None else None,
                new_text=_text(new_data) if new_data is not None else None,
                atoms=[],
            )

            def atom(kind, patch, old_start=0, new_start=0, old_count=0, new_count=0):
                file["atoms"].append(
                    dict(
                        id=_identity(fid, kind, patch),
                        kind=kind,
                        patch=patch,
                        old_start=old_start,
                        new_start=new_start,
                        old_count=old_count,
                        new_count=new_count,
                    )
                )

            if code[0] in "ARCDT" or item["old_mode"] != item["new_mode"]:
                atom(
                    "metadata",
                    "%s: %s -> %s; mode %s -> %s; object %s -> %s"
                    % (
                        status,
                        item["old_path"] or "(absent)",
                        item["path"],
                        item["old_mode"],
                        item["new_mode"],
                        item["old_oid"],
                        item["new_oid"],
                    ),
                )
            if "160000" in (item["old_mode"], item["new_mode"]):
                atom(
                    "submodule",
                    "Submodule commit %s -> %s. Nested contents are not included; configure the submodule as a separate repository."
                    % (item["old_oid"], item["new_oid"]),
                )
            elif (
                "\nBinary files " in canonical_file
                or "\nGIT binary patch" in canonical_file
                or (old_data is not None and file["old_text"] is None)
                or (new_data is not None and file["new_text"] is None)
            ):
                atom(
                    "binary",
                    "Binary or non-UTF-8 content: %s (%s bytes) -> %s (%s bytes)."
                    % (
                        item["old_oid"],
                        len(old_data or b""),
                        item["new_oid"],
                        len(new_data or b""),
                    ),
                )
            else:
                old_oid = item["old_oid"] if old_data is not None else empty
                new_oid = item["new_oid"] if new_data is not None else empty
                patch = git.run(
                    "diff", *_DIFF, "--patch", old_oid, new_oid, "--"
                ).decode("utf-8")
                matches = list(_HUNK.finditer(patch))
                for pos, match in enumerate(matches):
                    end = (
                        matches[pos + 1].start()
                        if pos + 1 < len(matches)
                        else len(patch)
                    )
                    atom(
                        "text",
                        patch[match.start() : end],
                        int(match[1]),
                        int(match[3]),
                        int(match[2] or 1),
                        int(match[4] or 1),
                    )
                if len(matches) != len(_HUNK.findall(canonical_file)):
                    raise ValueError(
                        "Canonical Git hunks disagree for %r. Check diff attributes and retry."
                        % item["path"]
                    )
                hunk_count += len(matches)
            if not file["atoms"]:
                atom(
                    "metadata",
                    "Object %s -> %s; mode %s -> %s"
                    % (
                        item["old_oid"],
                        item["new_oid"],
                        item["old_mode"],
                        item["new_mode"],
                    ),
                )
            files.append(file)
        canonical_hunks = len(_HUNK.findall(canonical))
        contexts = []
        patterns = config.get("context_paths", [])
        tree_entries = (
            _entries(git, target) if patterns or destination is not None else {}
        )
        for name, (mode, oid) in sorted(tree_entries.items()):
            if any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns):
                data = _blob(git, oid, mode)
                contexts.append(
                    dict(
                        path=name,
                        oid=oid,
                        mode=mode,
                        text=_text(data) if data is not None else None,
                    )
                )
        result = dict(
            alias=alias,
            base_sha=base,
            target_id=target,
            target_commit=target_commit,
            files=files,
            contexts=contexts,
            captured_at=datetime.now(timezone.utc).isoformat(),
            include_untracked=bool(config.get("include_untracked", False)),
            diff_settings=_DIFF + _DETECT,
            canonical_patch=canonical,
            raw_counts=dict(
                files=len(manifest),
                atoms=sum(len(f["atoms"]) for f in files),
                text_hunks=hunk_count,
            ),
            reconciliation=dict(
                manifest=True, canonical_patch=True, canonical_hunks=canonical_hunks
            ),
            notes=[
                "Working targets use final on-disk tracked contents; nested submodule edits require a separate repository.",
                "Frozen text is complete UTF-8 without NUL bytes; binary and other encodings have identities and opaque atoms.",
            ],
        )
        if (
            git.run("rev-parse", "--verify", "--end-of-options", base_ref + "^{commit}")
            .strip()
            .decode("ascii")
            != base
        ):
            raise ValueError("Base ref moved during capture. Stop edits and retry.")
        if working:
            current_index = index_path.read_bytes() if index_path.exists() else None
            if current_index != original_index:
                raise ValueError(
                    "Repository index changed during capture. Stop edits and retry."
                )
            if current_index is not None:
                index.write_bytes(current_index)
            else:
                index.unlink(missing_ok=True)
            if (
                _working_tree(git, root, bool(config.get("include_untracked", False)))
                != target
            ):
                raise ValueError(
                    "Repository files changed during capture. Stop edits and retry."
                )
        elif (
            git.run(
                "rev-parse", "--verify", "--end-of-options", target_ref + "^{commit}"
            )
            .strip()
            .decode("ascii")
            != target_commit
        ):
            raise ValueError("Target ref moved during capture. Stop edits and retry.")
        if destination is not None:
            if (
                result["base_sha"] != expected["base_sha"]
                or result["target_id"] != expected["target_id"]
            ):
                raise ValueError(
                    "Repository inputs changed since this capture. Refresh before running a check."
                )
            _materialize(git, tree_entries, destination)
        return result


def capture_repo(config):
    """Return a complete, immutable JSON-serializable inventory or raise ValueError."""
    try:
        return _capture(config)
    except OSError as exc:
        raise ValueError(
            "Repository capture could not read selected files: %s. Check access and retry."
            % exc
        ) from exc


def _materialization_blobs(git, oids):
    if not oids:
        return
    sizes = git.run(
        "cat-file", "--batch-check", data=("\n".join(oids) + "\n").encode()
    ).splitlines()
    if len(sizes) != len(oids):
        raise ValueError("Git object sizes did not reconcile during materialization.")
    records = []
    for oid, line in zip(oids, sizes):
        fields = line.decode("ascii").split()
        if len(fields) != 3 or fields[:2] != [oid, "blob"]:
            raise ValueError("Missing blob %s during materialization." % oid)
        records.append((oid, int(fields[2])))
    # Bound batch memory to 8 MiB, except a single larger blob read on its own.
    start = 0
    while start < len(records):
        end, total = start, 0
        while end < len(records) and (
            end == start or total + records[end][1] <= 8 * 1024 * 1024
        ):
            total += records[end][1]
            end += 1
        batch = records[start:end]
        output = git.run(
            "cat-file",
            "--batch",
            data=("\n".join(oid for oid, _ in batch) + "\n").encode(),
        )
        offset = 0
        for position, (oid, size) in enumerate(batch):
            header_end = output.find(b"\n", offset)
            expected_header = ("%s blob %d" % (oid, size)).encode()
            if header_end < 0 or output[offset:header_end] != expected_header:
                raise ValueError(
                    "Git blob identity did not reconcile during materialization."
                )
            offset = header_end + 1
            data = output[offset : offset + size]
            offset += size
            if len(data) != size or output[offset : offset + 1] != b"\n":
                raise ValueError("Git blob was truncated during materialization.")
            offset += 1
            if position == len(batch) - 1 and offset != len(output):
                raise ValueError("Unexpected Git batch output during materialization.")
            yield data
        if offset != len(output):
            raise ValueError("Unexpected Git batch output during materialization.")
        start = end


def _materialize(git, entries, destination):
    dest = Path(destination)
    if dest.is_symlink():
        raise ValueError("Check destination must not be a symlink.")
    if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
        raise ValueError("Check destination must be a private empty directory.")
    # Reject symlinks and submodules before writing: trusted checks must not escape.
    if any(mode in ("120000", "160000") for mode, _ in entries.values()):
        raise ValueError(
            "Check materialization does not support symlinks or submodules. Run an explicitly trusted external check and record its evidence."
        )
    dest.mkdir(parents=True, exist_ok=True)
    ordered = sorted(entries.items())
    blobs = _materialization_blobs(git, [entry[1][1] for entry in ordered])
    for (name, (mode, oid)), data in zip(ordered, blobs):
        path = _safe_path(dest, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(data)
        path.chmod(0o755 if mode == "100755" else 0o644)


def materialize_repo(config, expected_repository_snapshot, destination):
    """Recheck the selected target and write its raw frozen files into an empty folder.

    Never executes checkout filters or hooks. Symlink/submodule targets fail closed.
    Returns the reconciled snapshot; callers own cleanup of the private destination.
    """
    return _capture(config, destination, expected_repository_snapshot)
