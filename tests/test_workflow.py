"""Exercise browser transport and CLI against a pair of real editable checkouts."""

import contextlib
from http.client import HTTPConnection
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import uuid
from unittest.mock import patch

from cor.assistance import packet
from cor.cli import main
from cor.demo import demo
from cor.engine import Engine
from cor.server import LocalServer, STATIC


class SharedWorkflow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.engine = Engine(self.home)
        self.server = LocalServer(0, self.engine)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(self.server.shutdown)
        self.cookie = ""
        conn = HTTPConnection("127.0.0.1", self.server.server_port, timeout=15)
        conn.request("GET", "/")
        response = conn.getresponse()
        self.assertEqual(response.status, 200)
        self.cookie = response.getheader("Set-Cookie").split(";")[0]
        self.assertIn(b'<div id="root"', response.read())
        conn.close()

    def api(self, method, path, payload=None):
        conn = HTTPConnection("127.0.0.1", self.server.server_port, timeout=60)
        try:
            headers = {"Cookie": self.cookie}
            if method == "POST":
                headers.update(
                    {"X-COR-Request": "1", "Content-Type": "application/json"}
                )
            conn.request(
                method,
                "/api" + path,
                json.dumps(payload) if payload is not None else None,
                headers,
            )
            response = conn.getresponse()
            raw = response.read()
            content = (
                json.loads(raw)
                if response.getheader("Content-Type").startswith("application/json")
                else raw.decode()
            )
            return response.status, content
        finally:
            conn.close()

    def cli(self, *args):
        out = io.StringIO()
        with (
            patch.dict("os.environ", {"COR_HOME": str(self.home)}),
            contextlib.redirect_stdout(out),
        ):
            self.assertEqual(main(args), 0)
        return out.getvalue()

    def test_browser_session_from_symlinked_installation(self):
        alias = self.home / "installed-assets"
        alias.symlink_to(STATIC, target_is_directory=True)
        with patch("cor.server.STATIC", alias):
            conn = HTTPConnection("127.0.0.1", self.server.server_port, timeout=15)
            self.addCleanup(conn.close)
            conn.request("GET", "/")
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            self.cookie = response.getheader("Set-Cookie").split(";")[0]
            response.read()
            self.assertEqual(self.api("GET", "/sessions"), (200, {"sessions": []}))

    def test_cross_client_fix_handoff_and_trusted_execution(self):
        code, v = self.api("POST", "/demo", {})
        self.assertEqual(code, 200)
        sid = v["id"]
        url = "/sessions/" + sid
        contract = next(u for u in v["units"] if u["contract_id"])
        self.assertTrue(any(f["blocking"] for f in contract["findings"]))
        payload = {
            "action": "request_changes",
            "reason": "Use the producer's job_id field.",
            "unit_id": contract["id"],
            "version": v["version"],
            "capture": v["capture"],
            "action_id": uuid.uuid4().hex,
        }
        status, first = self.api("POST", url + "/decisions", payload)
        self.assertEqual(status, 200)
        wrong = {**payload, "action": "approve", "action_id": uuid.uuid4().hex}
        self.assertEqual(self.api("POST", url + "/decisions", wrong)[0], 409)
        history = json.loads(self.cli("history", "--session", sid, "--json"))
        self.assertEqual(history[-1]["action"], "request_changes")
        portal = next(r for r in v["config"]["repos"] if r["alias"] == "portal")
        file = Path(portal["path"]) / "src/jobs/retry.ts"
        file.write_text(file.read_text().replace("result.jobId", "result.job_id"))
        before = self.api("GET", url + "/verify")[1]
        self.assertFalse(before["ready"])
        self.assertTrue(any("Live Git" in b for b in before["blockers"]))
        after = json.loads(self.cli("capture", "--session", sid, "--refresh", "--json"))
        self.assertNotEqual(after["capture"], first["capture"])
        self.assertEqual(
            self.api("GET", url + "?capture=" + first["capture"])[1]["capture"],
            first["capture"],
        )
        current = self.api("GET", url)[1]
        self.assertEqual(
            next(u for u in current["units"] if u["contract_id"])["status"], "stale"
        )
        self.assertFalse(
            any(f["blocking"] for u in current["units"] for f in u["findings"])
        )
        for u in current["units"]:
            self.cli(
                "review",
                "--session",
                sid,
                "--unit",
                u["id"],
                "--action",
                "approve",
                "--yes",
            )
        check = json.loads(
            self.cli(
                "check",
                "--session",
                sid,
                "--name",
                "retry",
                "--repo",
                "job-manager",
                "--yes",
                "--json",
                "--",
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                "tests",
            )
        )
        self.assertTrue(check["passed"])
        self.assertIn("Ran 1 test", check["output"])
        gate = self.api("GET", url + "/verify")[1]
        self.assertTrue(gate["ready"], gate)
        self.assertEqual(gate["counts"]["approved"], gate["counts"]["atoms"])
        ledger = self.api("GET", url + "/export?format=json")[1]
        self.assertTrue(ledger["verification"]["ready"])
        self.assertEqual(ledger["review"]["checks"][0]["exit_code"], 0)
        self.assertNotIn(
            str(self.home), self.cli("export", "--session", sid, "--format", "markdown")
        )

    def test_packet_import_is_evidence_bound_and_cannot_approve(self):
        view = demo(self.engine, self.home)
        path = "/sessions/" + view["id"]
        report = self.api("GET", path + "/packet")[1]
        self.assertIn(
            "sides",
            next(u for u in report["units"] if u["title"] == "Retry response field"),
        )
        unit = report["units"][0]
        imported = dict(
            report["report_format"],
            assessed=unit["atom_ids"],
            findings=[
                {
                    "unit_id": unit["id"],
                    "title": "Check the consumer fixture",
                    "detail": "Validate matching field names.",
                    "blocking": False,
                    "evidence": unit["atom_ids"][:1],
                }
            ],
        )
        status, after = self.api(
            "POST",
            path + "/import",
            dict(report=imported, capture=view["capture"], version=view["version"]),
        )
        self.assertEqual(status, 200, after)
        self.assertEqual(after["counts"]["approved"], 0)
        self.assertIn("independent-review", after["analysis_passes"])
        imported["findings"][0]["evidence"] = ["unknown-atom"]
        status, _ = self.api(
            "POST",
            path + "/import",
            dict(report=imported, capture=view["capture"], version=after["version"]),
        )
        self.assertEqual(status, 400)
        self.assertEqual(self.engine.revision(view["id"])["version"], after["version"])

    def test_packet_omits_private_files_and_redacts_known_secrets(self):
        view = demo(self.engine, self.home)
        repo = next(r for r in view["config"]["repos"] if r["alias"] == "portal")
        (Path(repo["path"]) / ".env.local").write_text("API_KEY=example-private-file")
        (Path(repo["path"]) / "config.ts").write_text(
            "const token = 'example-private-literal';\n"
        )
        new = self.engine.refresh(view["id"], view["version"])
        payload = json.dumps(packet(new))
        self.assertNotIn("example-private-file", payload)
        self.assertNotIn("example-private-literal", payload)
        self.assertIn("sensitive line omitted", payload)
        portable = self.engine.export(view["id"], "json")
        self.assertNotIn("example-private-file", portable)
        self.assertNotIn("example-private-literal", portable)
