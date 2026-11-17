"""Create a small, editable pair of Git repositories owned by this application."""

import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

_LOCK = threading.Lock()


def data_home():
    return (
        Path(os.environ.get("COR_HOME", "~/.local/share/code-ownership-review"))
        .expanduser()
        .resolve()
    )


def _write(repo, name, body):
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _base(repo, files):
    repo.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)

    def git(*args):
        subprocess.run(
            [
                "git",
                "-c",
                "core.hooksPath=" + os.devnull,
                "-c",
                "commit.gpgSign=false",
                "-c",
                "user.name=Code Ownership Review",
                "-c",
                "user.email=demo@localhost",
                *args,
            ],
            cwd=repo,
            env=env,
            capture_output=True,
            check=True,
        )

    git("init", "-q")
    for name, body in files.items():
        _write(repo, name, body)
    git("add", "--all")
    git("commit", "-qm", "Base before retry support")


def demo(engine, home=None):
    # A unique directory for each initialization keeps concurrent launchers isolated.
    root = Path(home or data_home()).expanduser().resolve()
    with _LOCK:
        for entry in engine.list_sessions():
            v = engine.get(entry["id"])
            if (
                any(
                    str(r.get("path", "")).startswith(str(root / "examples") + os.sep)
                    for r in v["config"]["repos"]
                )
                and v["title"] == "Retry failed jobs"
            ):
                return v
        examples = root / "examples"
        examples.mkdir(parents=True, exist_ok=True, mode=0o700)
        folder = Path(tempfile.mkdtemp(prefix="retry-", dir=examples))
        backend, portal = folder / "job-manager", folder / "portal"
        try:
            _base(
                backend,
                {
                    "api/retry.py": "def retry_job(job, actor):\n    raise NotImplementedError('Retry is unavailable')\n",
                    "dal/jobs.py": "def get_client():\n    return shared_client\n",
                    "tests/test_retry.py": "import unittest\n",
                },
            )
            _base(
                portal,
                {
                    "src/jobs/retry.ts": "export async function retryJob(id: string) {\n  throw new Error('Retry is unavailable');\n}\n"
                },
            )
            _write(
                backend,
                "api/retry.py",
                """def retry_job(job, actor):
    job.require_access(actor)
    if job.state != "failed":
        raise ValueError("Only failed jobs can be retried")
    job.enqueue_once()
    return {"job_id": job.id}
""",
            )
            _write(
                backend,
                "retry/store.py",
                """from pymongo import MongoClient

class RetryStore:
    def __init__(self, uri):
        self.client = MongoClient(uri)
""",
            )
            _write(
                backend,
                "tests/test_retry.py",
                """import unittest
from types import SimpleNamespace
from api.retry import retry_job

class RetryTests(unittest.TestCase):
    def test_response_id(self):
        job = SimpleNamespace(id="j-12", state="failed", require_access=lambda a: None, enqueue_once=lambda: None)
        self.assertEqual(retry_job(job, "operator"), {"job_id": "j-12"})
""",
            )
            _write(
                portal,
                "src/jobs/retry.ts",
                """export async function retryJob(id: string) {
  const response = await fetch(`/api/jobs/${id}/retry`, { method: 'POST' });
  if (!response.ok) throw new Error('Retry failed');
  const result = await response.json();
  return result.jobId;
}
""",
            )
            return engine.create(
                {
                    "title": "Retry failed jobs",
                    "objective": "Let an authorized operator retry a failed job and see its identifier in the portal.",
                    "criteria": [
                        "Only a failed job can be retried.",
                        "Reuse the existing execution and persistence paths.",
                        "The portal displays the identifier returned by the job service.",
                    ],
                    "repos": [
                        {
                            "alias": r.name,
                            "path": str(r),
                            "base": "HEAD",
                            "target": "WORKTREE",
                            "include_untracked": True,
                        }
                        for r in (backend, portal)
                    ],
                    "contracts": [
                        {
                            "id": "C-1",
                            "title": "Retry response field",
                            "producer": {"repo": "job-manager", "path": "api/retry.py"},
                            "consumer": {"repo": "portal", "path": "src/jobs/retry.ts"},
                            "expectation": "The portal must read the job identifier returned by the service.",
                        }
                    ],
                }
            )
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise
