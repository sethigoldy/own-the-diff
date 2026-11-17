"""Run only user-selected, trusted commands in a disposable captured workspace."""

import os
import signal
import subprocess
import tempfile
from pathlib import Path

from .engine import Conflict
from .inventory import materialize_repo


def run_check(engine, sid, payload):
    v = engine.get(sid)
    if payload.get("capture") != v["capture"] or payload.get("version") != v["version"]:
        raise Conflict(
            "The review changed. Reopen this capture before running a check."
        )
    name, alias, argv = payload.get("name"), payload.get("repo"), payload.get("argv")
    if (
        not isinstance(name, str)
        or not name.strip()
        or not isinstance(argv, list)
        or not argv
        or len(argv) > 128
    ):
        raise ValueError("Provide a check name, repository and command arguments.")
    if (
        not all(isinstance(a, str) and len(a) <= 32768 and "\0" not in a for a in argv)
        or not argv[0]
    ):
        raise ValueError(
            "Each argument must be a string and the executable must be nonempty."
        )
    configs = v["config"]["repos"]
    if alias not in {r["alias"] for r in configs}:
        raise ValueError("Select a repository in this review.")
    with tempfile.TemporaryDirectory(prefix="cor-check-") as work:
        checkout = Path(work) / "workspace"
        checkout.mkdir()
        for cfg in configs:
            repo = next(r for r in v["repositories"] if r["alias"] == cfg["alias"])
            if (
                not cfg["alias"]
                or cfg["alias"] in (".", "..")
                or Path(cfg["alias"]).name != cfg["alias"]
            ):
                raise ValueError("A repository alias cannot be used as a folder name.")
            dest = checkout / cfg["alias"]
            dest.mkdir()
            materialize_repo(cfg, repo, dest)
        with tempfile.TemporaryFile() as log:
            try:
                proc = subprocess.Popen(
                    argv,
                    cwd=checkout / alias,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            except OSError as e:
                raise ValueError(f"Cannot start check: {e}") from e
            timed_out = False
            try:
                proc.wait(timeout=120)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
            size = log.tell()
            log.seek(max(0, size - 16384))
            output = (
                "[Last 16 KiB of output]\n" if size > 16384 else ""
            ) + log.read().decode(errors="replace")
            if timed_out:
                output += "\nCheck exceeded 120 seconds."
            return engine.record_check(
                sid,
                {
                    "version": v["version"],
                    "capture": v["capture"],
                    "name": name.strip(),
                    "repo": alias,
                    "passed": proc.returncode == 0 and not timed_out,
                    "exit_code": proc.returncode,
                    "command": argv,
                    "output": output,
                },
            )
