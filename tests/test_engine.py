import copy
import json
import tempfile
import unittest
from unittest.mock import patch

from cor.engine import Engine, Conflict


def file(repo, path, text, oid="new"):
    return dict(
        id=repo + ":" + path,
        repo=repo,
        path=path,
        old_path=None,
        status="M",
        old_oid="old",
        new_oid=oid,
        old_mode="100644",
        new_mode="100644",
        atoms=[
            dict(
                id=repo + ":" + path + ":" + oid,
                kind="text",
                patch="@@ -1 +1 @@\n-old\n+" + text,
                old_start=1,
                new_start=1,
            )
        ],
    )


def inventories():
    return [
        dict(
            alias="api",
            base_sha="base",
            target_id="one",
            files=[file("api", "retry.py", 'return {"job_id": job.id}')],
        ),
        dict(
            alias="portal",
            base_sha="base",
            target_id="two",
            files=[
                file("portal", "retry.ts", "return result.jobId"),
                file("portal", "other.ts", "unrelated"),
            ],
        ),
    ]


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.engine = Engine(self.temp.name)
        self.inventory = inventories()
        self.capture = patch.object(
            Engine, "_capture", side_effect=lambda config: copy.deepcopy(self.inventory)
        )
        self.capture.start()
        self.addCleanup(self.capture.stop)
        self.config = dict(
            title="Retry",
            objective="Retry failed jobs using the existing execution path",
            criteria=["Preserve job identifier"],
            repos=[
                dict(alias="api", path="/private/api"),
                dict(alias="portal", path="/private/portal"),
            ],
            contracts=[
                dict(
                    id="C1",
                    title="Retry response",
                    producer=dict(repo="api", path="retry.py"),
                    consumer=dict(repo="portal", path="retry.ts"),
                    expectation="Consumer receives identifier",
                )
            ],
        )
        self.view = self.engine.create(self.config)

    def decide(self, unit, action="approve", reason="", **extra):
        self.view = self.engine.decide(
            self.view["id"],
            dict(
                unit_id=unit["id"],
                action=action,
                reason=reason,
                version=self.view["version"],
                capture=self.view["capture"],
                action_id="a" + str(self.view["version"]),
                **extra,
            ),
        )
        return self.view

    def test_contract_mismatch_full_coverage_and_false_positive_disposition(self):
        self.assertEqual(self.view["counts"]["represented"], 3)
        self.assertEqual(len(self.view["units"]), 2)
        contract = self.view["units"][0]
        self.assertIn("job_id / jobId", contract["findings"][0]["title"])
        self.decide(contract)
        self.decide(self.view["units"][1])
        self.assertFalse(self.engine.verify(self.view["id"])["ready"])
        self.decide(
            contract,
            "dismiss",
            "Adapter performs conversion; inspected response fixture",
            finding_id=contract["findings"][0]["id"],
        )
        self.assertTrue(self.engine.verify(self.view["id"])["ready"])
        self.assertEqual(self.view["counts"]["approved"], 3)

    def test_refresh_stales_dependents_carries_unrelated_and_preserves_history(self):
        contract, other = self.view["units"]
        self.decide(contract)
        self.decide(other)
        old = copy.deepcopy(self.view)
        self.inventory[0]["files"][0] = file(
            "api", "retry.py", 'return {"job_id": str(job.id)}', "changed"
        )
        self.inventory[0]["target_id"] = "changed"
        self.view = self.engine.refresh(self.view["id"], self.view["version"])
        self.assertEqual(
            [u["status"] for u in self.view["units"]], ["stale", "approved"]
        )
        self.assertEqual(self.engine.get(old["id"], old["capture"]), old)
        self.assertEqual(Engine(self.temp.name).get(self.view["id"]), self.view)

    def test_base_drift_reopens_relevant_units(self):
        self.decide(self.view["units"][0])
        self.inventory[0]["base_sha"] = "next"
        self.view = self.engine.refresh(self.view["id"], self.view["version"])
        self.assertEqual(self.view["units"][0]["status"], "stale")

    def test_optimistic_writes_and_idempotency(self):
        payload = dict(
            unit_id=self.view["units"][0]["id"],
            action="approve",
            reason="",
            version=self.view["version"],
            capture=self.view["capture"],
            action_id="same",
        )
        first = self.engine.decide(self.view["id"], payload)
        self.assertEqual(self.engine.decide(self.view["id"], payload), first)
        self.assertEqual(len(self.engine.history(self.view["id"])), 2)
        with self.assertRaises(Conflict):
            self.engine.decide(self.view["id"], dict(payload, action_id="different"))
        with self.assertRaises(Conflict):
            self.engine.decide(self.view["id"], dict(payload, reason="changed"))

    def test_failed_capture_does_not_publish(self):
        before = self.engine.get(self.view["id"])
        with patch.object(
            Engine, "_capture", side_effect=ValueError("second checkout unavailable")
        ):
            with self.assertRaises(ValueError):
                self.engine.refresh(self.view["id"], self.view["version"])
        self.assertEqual(self.engine.get(self.view["id"]), before)

    def test_missing_counterpart_explicit_and_context_satisfies_side(self):
        self.inventory[1]["files"] = self.inventory[1]["files"][1:]
        self.view = self.engine.refresh(self.view["id"], self.view["version"])
        self.assertFalse(self.view["units"][0]["sides"]["consumer"]["available"])
        self.assertTrue(
            any(
                f["blocking"] and "Missing consumer" in f["title"]
                for f in self.view["units"][0]["findings"]
            )
        )
        self.inventory[1]["contexts"] = [
            dict(path="retry.ts", oid="ctx", text="return result.jobId", mode="100644")
        ]
        self.view = self.engine.refresh(self.view["id"], self.view["version"])
        self.assertTrue(self.view["units"][0]["sides"]["consumer"]["available"])
        self.assertTrue(
            any("mismatch" in f["title"] for f in self.view["units"][0]["findings"])
        )

    def test_exports_live_drift_and_privacy(self):
        self.inventory[0]["files"][0]["new_text"] = "unrelated full secret blob"
        self.view = self.engine.refresh(self.view["id"], self.view["version"])
        output = self.engine.export(self.view["id"], "json")
        self.assertNotIn("/private/api", output)
        self.assertNotIn("unrelated full secret blob", output)
        self.assertEqual(json.loads(output)["schema_version"], 1)
        self.inventory[0]["target_id"] = "drift"
        self.assertIn(
            "Live Git inputs", self.engine.export(self.view["id"], "markdown")
        )

    def test_analysis_validates_references_and_does_not_approve(self):
        u = self.view["units"][0]
        payload = dict(
            version=self.view["version"],
            capture=self.view["capture"],
            pass_name="scope",
            assessed=u["atom_ids"],
            unknown=[],
            findings=[
                dict(
                    unit_id=u["id"],
                    title="Question",
                    detail="Inspect lines",
                    blocking=False,
                    evidence=["invented"],
                )
            ],
        )
        with self.assertRaises(ValueError):
            self.engine.record_analysis(self.view["id"], payload)
        self.assertEqual(self.engine.get(self.view["id"]), self.view)
        payload["findings"][0]["evidence"] = u["atom_ids"]
        self.view = self.engine.record_analysis(self.view["id"], payload)
        self.assertEqual(self.view["counts"]["approved"], 0)
        self.assertEqual(
            self.view["analysis_passes"]["scope"]["assessed"], sorted(u["atom_ids"])
        )
        payload["version"] = self.view["version"]
        self.view = self.engine.record_analysis(self.view["id"], payload)
        self.assertEqual(
            sum(f["title"] == "Question" for f in self.view["units"][0]["findings"]), 1
        )

    def test_required_checks_bound_to_capture(self):
        self.config["required_checks"] = ["unit"]
        self.view = self.engine.create(self.config)
        self.assertTrue(
            any(
                "Required check" in b
                for b in self.engine.verify(self.view["id"])["blockers"]
            )
        )
        self.view = self.engine.record_check(
            self.view["id"],
            dict(
                version=self.view["version"],
                capture=self.view["capture"],
                name="unit",
                passed=True,
                command="python3 -m unittest",
                output="OK",
            ),
        )
        self.assertFalse(
            any(
                "Required check" in b
                for b in self.engine.verify(self.view["id"])["blockers"]
            )
        )
        self.view = self.engine.refresh(self.view["id"], self.view["version"])
        self.assertTrue(
            any(
                "Required check" in b
                for b in self.engine.verify(self.view["id"])["blockers"]
            )
        )

    def test_config_edit_is_atomic_and_reopens_approvals(self):
        self.decide(self.view["units"][0])
        old = copy.deepcopy(self.view)
        amended = copy.deepcopy(self.config)
        amended["objective"] = "Retry with an amended response contract"
        self.view = self.engine.update_config(
            self.view["id"], amended, self.view["version"]
        )
        self.assertEqual(self.view["units"][0]["status"], "stale")
        self.assertEqual(self.engine.get(old["id"], old["capture"]), old)
        for invalid in (".", "..", "../outside", "/root", "a/b"):
            amended["repos"][0]["alias"] = invalid
            with self.assertRaises(ValueError):
                self.engine.update_config(
                    self.view["id"], amended, self.view["version"]
                )

    def test_config_amendment_regroups_new_external_contract(self):
        amended = copy.deepcopy(self.config)
        amended["contracts"].append(
            dict(
                id="external",
                title="External integration",
                expectation="Partner consumes retry",
                producer=dict(repo="api", path="retry.py"),
                consumer=dict(repo="external", path="caller.py"),
            )
        )
        self.view = self.engine.update_config(
            self.view["id"], amended, self.view["version"]
        )
        external = next(u for u in self.view["units"] if u["contract_id"] == "external")
        self.assertFalse(external["sides"]["consumer"]["available"])
        self.assertTrue(external["findings"][0]["blocking"])

    def test_imported_finding_capture_links_remain_bounded(self):
        u = self.view["units"][0]
        self.view = self.engine.record_analysis(
            self.view["id"],
            dict(
                version=self.view["version"],
                capture=self.view["capture"],
                pass_name="contracts",
                assessed=u["atom_ids"],
                unknown=[],
                findings=[
                    dict(
                        unit_id=u["id"],
                        title="Interface check",
                        detail="Review conversion",
                        blocking=True,
                        evidence=u["atom_ids"],
                    )
                ],
            ),
        )
        origin = self.view["capture"]
        for iteration in range(3):
            self.inventory[0]["files"][0] = file(
                "api",
                "retry.py",
                'return {"job_id": job.id + %s}' % iteration,
                str(iteration),
            )
            self.view = self.engine.refresh(self.view["id"], self.view["version"])
            imported = next(
                f for f in self.view["units"][0]["findings"] if f.get("pass_name")
            )
            self.assertEqual(imported["capture"], self.view["capture"])
            self.assertEqual(imported["origin_capture"], origin)
            self.assertEqual(
                imported["detail"].count("Prior analysis needs reevaluation"), 1
            )

    def test_check_argv_and_actual_status(self):
        self.view = self.engine.record_check(
            self.view["id"],
            dict(
                version=self.view["version"],
                capture=self.view["capture"],
                name="unit",
                passed=True,
                repo="api",
                exit_code=0,
                command=["python3", "-m", "unittest"],
                output="OK",
            ),
        )
        self.assertEqual(self.view["checks"][0]["exit_code"], 0)
        self.assertEqual(
            self.engine.verify(self.view["id"])["tests"], "recorded checks: unit passed"
        )
        self.assertIn("unit passed", self.engine.export(self.view["id"], "markdown"))

    def test_unrelated_file_changes_preserve_contract_disposition(self):
        contract = self.view["units"][0]
        self.decide(
            contract,
            "dismiss",
            "Adapter inspected",
            finding_id=contract["findings"][0]["id"],
        )
        self.decide(contract)
        self.inventory[1]["files"][1] = file(
            "portal", "other.ts", "changed separately", "next"
        )
        self.inventory[1]["target_id"] = "next"
        self.view = self.engine.refresh(self.view["id"], self.view["version"])
        self.assertEqual(self.view["units"][0]["status"], "approved")
        self.assertEqual(
            self.view["units"][0]["findings"][0]["disposition"]["reason"],
            "Adapter inspected",
        )
        self.inventory[0]["files"][0] = file(
            "api", "retry.py", 'return {"job_id": str(job.id)}', "next"
        )
        self.view = self.engine.refresh(self.view["id"], self.view["version"])
        self.assertEqual(self.view["units"][0]["status"], "stale")
        self.assertNotIn("disposition", self.view["units"][0]["findings"][0])

    def test_surrogate_filename_persists_and_exports(self):
        self.inventory[1]["files"].append(file("portal", "bad-\udcff.ts", "addition"))
        self.view = self.engine.refresh(self.view["id"], self.view["version"])
        self.assertEqual(Engine(self.temp.name).get(self.view["id"]), self.view)
        self.assertIn(
            "bad-\udcff.ts",
            json.loads(self.engine.export(self.view["id"], "json"))["review"][
                "repositories"
            ][1]["files"][-1]["path"],
        )

    def test_revision_summary_and_transactional_delete(self):
        self.assertEqual(
            self.engine.revision(self.view["id"]),
            dict(version=self.view["version"], capture=self.view["capture"]),
        )
        self.assertEqual(self.engine.list_sessions()[0]["title"], "Retry")
        with self.assertRaises(Conflict):
            self.engine.delete(self.view["id"], self.view["version"] - 1)
        self.decide(self.view["units"][0])
        self.engine.delete(self.view["id"], self.view["version"])
        self.assertEqual(self.engine.list_sessions(), [])
        with self.assertRaises(KeyError):
            self.engine.get(self.view["id"])
        with self.engine._connect() as db:
            for table in ("sessions", "captures", "events", "actions"):
                self.assertEqual(
                    db.execute("SELECT count(*) FROM " + table).fetchone()[0], 0
                )

    def test_untrusted_analysis_shapes_raise_value_error(self):
        base = dict(
            version=self.view["version"],
            capture=self.view["capture"],
            pass_name="independent",
            findings=[],
            assessed=[],
            unknown=[],
        )
        mutations = [
            dict(assessed="bad"),
            dict(unknown=[{}]),
            dict(findings={}),
            dict(findings=[None]),
            dict(
                findings=[
                    dict(unit_id=[], evidence=[], title="a", detail="b", blocking=True)
                ]
            ),
            dict(
                findings=[
                    dict(
                        unit_id=self.view["units"][0]["id"],
                        evidence=[{}],
                        title="a",
                        detail="b",
                        blocking=True,
                    )
                ]
            ),
        ]
        for mutation in mutations:
            with self.assertRaises(ValueError):
                self.engine.record_analysis(self.view["id"], dict(base, **mutation))
        self.assertEqual(self.engine.get(self.view["id"]), self.view)

    def test_optional_config_defaults_and_low_risk_path_signals(self):
        minimal = dict(
            title="Minimal",
            objective="Inspect a small change",
            repos=[dict(alias="api", path="/private/api")],
        )
        self.inventory = self.inventory[:1]
        self.inventory[0]["files"] = [
            file("api", "tests/test_retry.py", "assert retry()")
        ]
        v = self.engine.create(minimal)
        self.assertEqual(v["config"]["contracts"], [])
        self.assertEqual(v["units"][0]["risk"], "low")
        self.assertIn("Test-path", v["units"][0]["risk_basis"])
        self.assertEqual(v["units"][0]["scope"]["classification"], "unknown")

    def test_literal_http_contract_suggestions_are_advisory(self):
        self.config["contracts"] = []
        self.inventory[0]["files"][0]["new_text"] = (
            '@app.post("/api/jobs/{job_id}/retry")\ndef retry(job_id):\n    return {"job_id": job_id}\n'
        )
        self.inventory[1]["files"][0]["new_text"] = (
            'export async function retry(id) {\n  return fetch(`/api/jobs/${id}/retry`, { method: "POST" });\n}\n'
        )
        self.view = self.engine.create(self.config)
        suggestions = self.view["suggested_contracts"]
        self.assertEqual(len(suggestions), 1)
        suggestion = suggestions[0]
        self.assertEqual(suggestion["title"], "POST /api/jobs/{param}/retry")
        self.assertEqual(suggestion["provenance"], "inferred")
        self.assertEqual([e["line"] for e in suggestion["evidence"]], [1, 2])
        self.assertEqual(self.view["config"]["contracts"], [])
        self.assertTrue(all(u["contract_id"] is None for u in self.view["units"]))
        self.config["contracts"] = [suggestion]
        self.view = self.engine.update_config(
            self.view["id"], self.config, self.view["version"]
        )
        self.assertEqual(self.view["suggested_contracts"], [])
        self.assertTrue(
            any(u["contract_id"] == suggestion["id"] for u in self.view["units"])
        )

    def test_ambiguous_unrelated_commented_and_dynamic_routes_not_suggested(self):
        from cor.analysis import suggest_contracts

        self.config["contracts"] = []
        producer = self.inventory[0]["files"][0]
        consumer = self.inventory[1]["files"][0]
        producer["new_text"] = '@app.get("/jobs")\ndef jobs(): pass\n'
        for source in (
            'fetch("/other")',
            'fetch("/jobs", {method: "POST"})',
            '// fetch("/jobs")',
            "const example = 'fetch(\"/jobs\")';",
            "fetch(endpoint)",
            'fetch("/jobs", {method: verb})',
        ):
            consumer["new_text"] = source
            self.assertEqual(suggest_contracts(self.config, self.inventory), [])
        consumer["new_text"] = 'fetch("/jobs")'
        producer["new_text"] += '@app.get("/jobs")\ndef duplicate(): pass\n'
        self.assertEqual(suggest_contracts(self.config, self.inventory), [])
        producer["new_text"] = 'app.get("/jobs", handler);'
        producer["path"] = "routes.js"
        self.assertEqual(len(suggest_contracts(self.config, self.inventory)), 1)
        consumer["new_text"] += '\nfetch("/jobs")'
        self.assertEqual(suggest_contracts(self.config, self.inventory), [])

    def test_shared_atoms_count_once_but_pending_overlap_blocks(self):
        self.config["contracts"].append(
            dict(self.config["contracts"][0], id="C2", title="Another dependency")
        )
        self.view = self.engine.create(self.config)
        self.decide(self.view["units"][0])
        self.assertEqual(self.view["counts"]["approved"], 2)
        self.assertTrue(
            any("pending" in b for b in self.engine.verify(self.view["id"])["blockers"])
        )


class ExternalContractAcceptanceTests(unittest.TestCase):
    def test_real_source_shared_multiple_consumers_and_unavailable_external(self):
        import subprocess
        from pathlib import Path

        with tempfile.TemporaryDirectory() as root:
            roots = {}
            for alias in ("source", "shared", "consumer-a", "consumer-b"):
                path = Path(root) / alias
                path.mkdir()
                roots[alias] = path
                subprocess.run(["git", "init", "-q", str(path)], check=True)
                (path / "interface.py").write_text("def value():\n    return 1\n")
                subprocess.run(["git", "-C", str(path), "add", "."], check=True)
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(path),
                        "-c",
                        "user.name=Reviewer",
                        "-c",
                        "user.email=reviewer@localhost",
                        "-c",
                        "commit.gpgsign=false",
                        "commit",
                        "-qm",
                        "base",
                    ],
                    check=True,
                )
            (roots["source"] / "interface.py").write_text(
                "def value():\n    return 2\n"
            )
            (roots["consumer-a"] / "interface.py").write_text(
                "def value():\n    return 3\n"
            )

            def edge(identifier, producer, consumer):
                return dict(
                    id=identifier,
                    title=identifier,
                    expectation="Consumer preserves the shared value contract",
                    producer=dict(repo=producer, path="interface.py"),
                    consumer=dict(repo=consumer, path="interface.py"),
                )

            config = dict(
                title="Fan-out feature",
                objective="Carry value through shared code to every consumer",
                repos=[
                    dict(alias=alias, path=str(path)) for alias, path in roots.items()
                ],
                contracts=[
                    edge("source-shared", "source", "shared"),
                    edge("shared-a", "shared", "consumer-a"),
                    edge("shared-b", "shared", "consumer-b"),
                    edge("shared-external", "shared", "external-partner"),
                ],
            )
            engine = Engine(Path(root) / "ledger")
            view = engine.create(config)
            self.assertEqual(len(view["units"]), 4)
            unavailable = next(
                u for u in view["units"] if u["contract_id"] == "shared-external"
            )
            self.assertFalse(unavailable["sides"]["consumer"]["available"])
            self.assertTrue(unavailable["sides"]["producer"]["available"])
            self.assertEqual(unavailable["atom_ids"], [])
            self.assertTrue(unavailable["findings"][0]["blocking"])
            unchanged = next(u for u in view["units"] if u["contract_id"] == "shared-b")
            self.assertTrue(unchanged["sides"]["consumer"]["available"])
            self.assertEqual(unchanged["atom_ids"], [])
            for unit in view["units"]:
                view = engine.decide(
                    view["id"],
                    dict(
                        unit_id=unit["id"],
                        action="approve",
                        version=view["version"],
                        capture=view["capture"],
                        action_id=unit["id"],
                    ),
                )
            verification = engine.verify(view["id"])
            self.assertFalse(verification["ready"])
            self.assertTrue(
                any("Missing consumer" in b for b in verification["blockers"])
            )
            bad = copy.deepcopy(config)
            bad["repos"].append(
                dict(alias="missing-configured", path=str(Path(root) / "absent"))
            )
            with self.assertRaises(ValueError):
                engine.create(bad)
            self.assertEqual(len(engine.list_sessions()), 1)


if __name__ == "__main__":
    unittest.main()
