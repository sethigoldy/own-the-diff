import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from cor.inventory import capture_repo, materialize_repo


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.org")
        self.git("config", "user.name", "Test")
        self.write("a.txt", "one\ntwo\nthree\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.config = dict(
            alias="test", path=str(self.root), base="HEAD", target="WORKTREE"
        )

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.root), *args], stderr=subprocess.PIPE
        )

    def write(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data.encode() if isinstance(data, str) else data)
        return path

    def capture(self, **kwargs):
        return capture_repo(dict(self.config, **kwargs))

    def test_final_worktree_and_private_index_and_objects(self):
        self.write("a.txt", "staged\n")
        self.git("add", "a.txt")
        self.write("a.txt", "final\n")
        before_index = (self.root / ".git/index").read_bytes()
        before_objects = sorted(
            p.relative_to(self.root / ".git/objects")
            for p in (self.root / ".git/objects").rglob("*")
            if p.is_file()
        )
        result = self.capture()
        self.assertEqual(result["files"][0]["new_text"], "final\n")
        self.assertEqual(before_index, (self.root / ".git/index").read_bytes())
        self.assertEqual(
            before_objects,
            sorted(
                p.relative_to(self.root / ".git/objects")
                for p in (self.root / ".git/objects").rglob("*")
                if p.is_file()
            ),
        )
        self.assertEqual(self.git("show", ":a.txt"), b"staged\n")
        self.assertEqual(result["raw_counts"]["text_hunks"], 1)
        self.assertEqual(result["files"][0]["id"], self.capture()["files"][0]["id"])
        json.dumps(result)

    def test_untracked_names_empty_binary_and_symlink(self):
        self.write("space ü\nname.txt", "hello\n")
        self.write("empty", b"")
        self.write("bytes", b"\0\xff")
        os.symlink("a.txt", self.root / "link")
        self.assertEqual(self.capture()["files"], [])
        files = {f["path"]: f for f in self.capture(include_untracked=True)["files"]}
        self.assertEqual(set(files), {"space ü\nname.txt", "empty", "bytes", "link"})
        self.assertEqual(files["space ü\nname.txt"]["new_text"], "hello\n")
        self.assertEqual(files["link"]["new_mode"], "120000")
        self.assertTrue(any(a["kind"] == "binary" for a in files["bytes"]["atoms"]))
        self.assertTrue(files["empty"]["atoms"])

    def test_committed_target_ignores_worktree_and_context_is_frozen(self):
        self.write("b.py", "answer = 42\n")
        self.git("add", ".")
        self.git("commit", "-qm", "second")
        self.write("b.py", "unsaved = 1\n")
        result = self.capture(base="HEAD~1", target="HEAD", context_paths=["a.txt"])
        self.assertEqual(result["files"][0]["new_text"], "answer = 42\n")
        self.assertEqual(result["contexts"][0]["text"], "one\ntwo\nthree\n")
        self.assertIsNotNone(result["target_commit"])

    def test_rename_copy_delete_mode_and_hunk_identity(self):
        self.write("delete", "gone\n")
        self.write("executable", "mode only\n")
        self.git("add", ".")
        self.git("commit", "-qm", "more base")
        self.git("mv", "a.txt", "renamed.txt")
        self.write("copy.txt", "mode only\n")
        self.git("add", "copy.txt")
        (self.root / "delete").unlink()
        (self.root / "executable").chmod(0o755)
        files = {f["path"]: f for f in self.capture()["files"]}
        self.assertEqual(files["renamed.txt"]["status"], "renamed")
        self.assertEqual(files["renamed.txt"]["old_path"], "a.txt")
        self.assertEqual(files["copy.txt"]["status"], "copied")
        self.assertEqual(files["delete"]["status"], "deleted")
        self.assertEqual(files["delete"]["old_path"], "delete")
        self.assertEqual(files["executable"]["new_mode"], "100755")
        self.assertTrue(all(f["atoms"] for f in files.values()))
        ids = [a["id"] for f in files.values() for a in f["atoms"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_no_hook_filter_textconv_or_external_diff_execution(self):
        marker = self.root / "EXECUTED"
        script = self.write("evil.sh", '#!/bin/sh\ntouch "' + str(marker) + '"\ncat\n')
        script.chmod(0o755)
        self.git("config", "filter.evil.clean", str(script))
        self.git("config", "filter.evil.smudge", str(script))
        self.git("config", "diff.evil.textconv", str(script))
        self.git("config", "diff.evil.command", str(script))
        self.git("config", "diff.external", str(script))
        self.git("config", "core.fsmonitor", str(script))
        self.write(".gitattributes", "*.txt filter=evil diff=evil\n")
        self.write("a.txt", "changed\n")
        result = self.capture()
        self.assertEqual(result["files"][0]["new_text"], "changed\n")
        self.assertFalse(marker.exists())

    def test_unresolved_merge_is_actionable(self):
        oid = self.git("rev-parse", "HEAD:a.txt").strip()
        data = b"100644 " + oid + b" 1\ta.txt\n100644 " + oid + b" 2\ta.txt\n"
        subprocess.run(
            ["git", "-C", str(self.root), "update-index", "--index-info"],
            input=data,
            check=True,
        )
        with self.assertRaisesRegex(ValueError, "unresolved merge"):
            self.capture()

    def test_capture_detects_edits_during_snapshot(self):
        from cor import inventory

        real = inventory._working_tree
        calls = []

        def changing(*args):
            tree = real(*args)
            calls.append(tree)
            if len(calls) == 1:
                self.write("a.txt", "raced\n")
            return tree

        with patch.object(inventory, "_working_tree", changing):
            with self.assertRaisesRegex(ValueError, "changed during capture"):
                self.capture()

    def test_reconciliation_failure_rejected(self):
        from cor import inventory

        self.write("a.txt", "changed\n")
        run = inventory._Git.run

        def broken(git, *args, **kwargs):
            if "--name-status" in args:
                return b""
            return run(git, *args, **kwargs)

        with patch.object(inventory._Git, "run", broken):
            with self.assertRaisesRegex(ValueError, "manifests disagree"):
                self.capture()

    def test_materialize_exact_capture_without_git_directory(self):
        self.write("a.txt", "frozen\n")
        snapshot = self.capture()
        destination = Path(self.temp.name) / "check"
        materialize_repo(self.config, snapshot, destination)
        self.assertEqual((destination / "a.txt").read_text(), "frozen\n")
        self.assertFalse((destination / ".git").exists())
        self.write("a.txt", "drift\n")
        with self.assertRaisesRegex(ValueError, "changed since"):
            materialize_repo(self.config, snapshot, Path(self.temp.name) / "check2")

    def test_materialize_rejects_symlinks(self):
        os.symlink("/tmp", self.root / "link")
        config = dict(self.config, include_untracked=True)
        snapshot = capture_repo(config)
        with self.assertRaisesRegex(ValueError, "symlinks or submodules"):
            materialize_repo(config, snapshot, Path(self.temp.name) / "check")

    def test_split_index_and_linked_worktree_stay_untouched(self):
        self.git("update-index", "--split-index")
        before = {
            str(p.relative_to(self.root / ".git")): p.read_bytes()
            for p in (self.root / ".git").rglob("*")
            if p.is_file()
        }
        self.write("a.txt", "split final\n")
        self.assertEqual(self.capture()["files"][0]["new_text"], "split final\n")
        after = {
            str(p.relative_to(self.root / ".git")): p.read_bytes()
            for p in (self.root / ".git").rglob("*")
            if p.is_file()
        }
        self.assertEqual(before, after)
        linked = Path(self.temp.name) / "linked"
        self.git("worktree", "add", "-qb", "linked", str(linked))
        (linked / "a.txt").write_text("linked final\n")
        result = capture_repo(dict(self.config, path=str(linked)))
        self.assertEqual(result["files"][0]["new_text"], "linked final\n")

    def test_binary_attribute_remains_explicit_with_frozen_text(self):
        self.write(".gitattributes", "*.txt -diff\n")
        self.write("a.txt", "changed\n")
        file = self.capture()["files"][0]
        self.assertEqual(file["new_text"], "changed\n")
        self.assertTrue(any(a["kind"] == "binary" for a in file["atoms"]))

    def test_separated_hunks_are_distinct_and_complete(self):
        self.write("a.txt", "".join("line %d\n" % n for n in range(40)))
        self.git("add", "a.txt")
        self.git("commit", "-qm", "long file")
        lines = (self.root / "a.txt").read_text().splitlines(True)
        lines[1], lines[35] = "first edit\n", "last edit\n"
        self.write("a.txt", "".join(lines))
        result = self.capture()
        hunks = [a for a in result["files"][0]["atoms"] if a["kind"] == "text"]
        self.assertEqual(len(hunks), 2)
        self.assertEqual(result["reconciliation"]["canonical_hunks"], 2)
        self.assertNotEqual(hunks[0]["id"], hunks[1]["id"])

    def test_many_unchanged_files_do_not_spawn_per_file_hash_processes(self):
        from cor import inventory

        for number in range(160):
            self.write("many/file-%03d.txt" % number, "unchanged %d\n" % number)
        self.git("add", ".")
        self.git("commit", "-qm", "many files")
        self.write("a.txt", "changed once\n")
        run, store = inventory._Git.run, inventory._Git.store_blob
        commands, written_counts = [], []

        def record(git, *args, **kwargs):
            commands.append(args[0])
            return run(git, *args, **kwargs)

        def record_store(git, *args, **kwargs):
            oid = store(git, *args, **kwargs)
            written_counts.append(len(git.written_blobs))
            return oid

        with (
            patch.object(inventory._Git, "run", record),
            patch.object(inventory._Git, "store_blob", record_store),
        ):
            result = self.capture()
        self.assertEqual(len(result["files"]), 1)
        self.assertNotIn("hash-object", commands)
        self.assertLess(len(commands), 45)
        self.assertEqual(
            max(written_counts), 2
        )  # one changed blob and the empty diff endpoint
        expected = (
            subprocess.check_output(
                ["git", "hash-object", "--stdin"], input=b"changed once\n"
            )
            .strip()
            .decode()
        )
        self.assertEqual(result["files"][0]["new_oid"], expected)
        commands.clear()
        destination = Path(self.temp.name) / "many-check"
        with patch.object(inventory._Git, "run", record):
            materialize_repo(self.config, result, destination)
        self.assertLessEqual(commands.count("cat-file"), 4)
        self.assertEqual(len(list((destination / "many").iterdir())), 160)

    def test_core_filemode_false_uses_indexed_mode_and_untracked_default(self):
        self.git("config", "core.filemode", "false")
        (self.root / "a.txt").chmod(0o755)
        self.assertEqual(self.capture()["files"], [])
        self.write("untracked", "executable\n").chmod(0o755)
        files = self.capture(include_untracked=True)["files"]
        self.assertEqual(files[0]["new_mode"], "100644")
        self.git("update-index", "--chmod=+x", "a.txt")
        (self.root / "a.txt").chmod(0o644)
        self.assertEqual(self.capture()["files"][0]["new_mode"], "100755")

    def test_large_binary_preserves_identity_and_opaque_evidence(self):
        data = b"\0" + bytes(range(256)) * 16384
        self.write("large.bin", data)
        result = self.capture(include_untracked=True)
        file = result["files"][0]
        expected = (
            subprocess.check_output(["git", "hash-object", "--stdin"], input=data)
            .strip()
            .decode()
        )
        self.assertEqual(file["new_oid"], expected)
        self.assertIsNone(file["new_text"])
        self.assertIn(
            "%d bytes" % len(data),
            next(a["patch"] for a in file["atoms"] if a["kind"] == "binary"),
        )
        destination = Path(self.temp.name) / "binary-check"
        materialize_repo(dict(self.config, include_untracked=True), result, destination)
        self.assertEqual((destination / "large.bin").read_bytes(), data)

    def test_sha256_repository_digest_matches_git(self):
        root = Path(self.temp.name) / "sha256"
        initialized = subprocess.run(
            ["git", "init", "-q", "--object-format=sha256", str(root)],
            capture_output=True,
        )
        if initialized.returncode:
            self.skipTest("Git has no SHA-256 repository support")
        (root / "text").write_text("base\n")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.org",
                "commit",
                "-qm",
                "base",
            ],
            check=True,
        )
        (root / "text").write_text("new\n")
        result = capture_repo(dict(self.config, path=str(root)))
        expected = (
            subprocess.check_output(
                ["git", "-C", str(root), "hash-object", "--stdin"], input=b"new\n"
            )
            .strip()
            .decode()
        )
        self.assertEqual(result["files"][0]["new_oid"], expected)
        self.assertEqual(len(expected), 64)

    def test_submodule_pointer_is_opaque(self):
        # A gitlink can be created without network access or cloning.
        oid = self.git("rev-parse", "HEAD").strip().decode()
        self.git("update-index", "--add", "--cacheinfo", "160000," + oid + ",module")
        (self.root / "module").mkdir()
        snapshot = self.capture()
        self.assertEqual(snapshot["files"][0]["new_mode"], "160000")
        self.assertTrue(
            any(a["kind"] == "submodule" for a in snapshot["files"][0]["atoms"])
        )


if __name__ == "__main__":
    unittest.main()
