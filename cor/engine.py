"""Shared local review engine backed by transactional SQLite and frozen evidence."""

import copy
from contextlib import contextmanager
import datetime
import json
import os
import re
from pathlib import Path
import sqlite3
import uuid

from .privacy import eligible, redact
from .analysis import analyze, dependency_fingerprint, digest, suggest_contracts


class Conflict(ValueError):
    """The client observed a superseded review version."""


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class Engine:
    def __init__(self, home=None):
        self.home = Path(
            home
            or os.environ.get(
                "COR_HOME", Path.home() / ".local/share/code-ownership-review"
            )
        )
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = self.home / "ledger.sqlite3"
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, view TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS captures (session TEXT, id TEXT, view TEXT NOT NULL, PRIMARY KEY(session,id));
                CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, session TEXT, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS actions (session TEXT, id TEXT, payload TEXT, PRIMARY KEY(session,id));
            """)
        os.chmod(self.db, 0o600)

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(str(self.db), timeout=30)
        try:
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                yield db
        finally:
            db.close()

    def _read(self, db, session, capture=None):
        row = (
            db.execute(
                "SELECT view FROM captures WHERE session=? AND id=?", (session, capture)
            ).fetchone()
            if capture
            else db.execute(
                "SELECT view FROM sessions WHERE id=?", (session,)
            ).fetchone()
        )
        if not row:
            raise KeyError("Unknown review or capture: " + str(capture or session))
        return json.loads(row[0])

    def _save(self, db, view):
        self._counts(view)
        encoded = json.dumps(view, ensure_ascii=True)
        db.execute(
            "INSERT OR REPLACE INTO sessions VALUES (?,?)", (view["id"], encoded)
        )
        db.execute(
            "INSERT OR REPLACE INTO captures VALUES (?,?,?)",
            (view["id"], view["capture"], encoded),
        )

    def _event(self, db, view, action, unit_id=None, reason="", **extra):
        event = dict(
            time=now(),
            action=action,
            unit_id=unit_id,
            reason=reason,
            capture=view["capture"],
            **extra,
        )
        view["events"].append(event)
        db.execute(
            "INSERT INTO events(session,payload) VALUES (?,?)",
            (view["id"], json.dumps(event)),
        )

    @staticmethod
    def _config(config):
        config = copy.deepcopy(config)
        if not isinstance(config, dict) or any(
            not isinstance(config.get(k), str) or not config[k].strip()
            for k in ("title", "objective")
        ):
            raise ValueError("A title and confirmed objective are required")
        if not isinstance(config.get("repos"), list) or not config["repos"]:
            raise ValueError("Configure at least one repository")
        for key in ("criteria", "required_checks", "required_passes"):
            if not isinstance(config.get(key, []), list) or not all(
                isinstance(x, str) and x.strip() for x in config.get(key, [])
            ):
                raise ValueError(key + " must be a list of nonempty strings")
        aliases = set()
        for repo in config["repos"]:
            if not isinstance(repo, dict):
                raise ValueError("Repository configuration must be an object")
            alias = repo.get("alias")
            if (
                not isinstance(alias, str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", alias)
                or alias in aliases
            ):
                raise ValueError("Repository aliases must be unique safe folder names")
            if (
                not isinstance(repo.get("path"), str)
                or not repo["path"].strip()
                or "\x00" in repo["path"]
            ):
                raise ValueError("Repositories require local paths")
            aliases.add(alias)
            repo["path"] = str(Path(repo["path"]).expanduser().resolve())
            repo.setdefault("base", "HEAD")
            repo.setdefault("target", "WORKTREE")
            repo.setdefault("include_untracked", False)
            if any(
                not isinstance(repo[k], str) or not repo[k].strip() or "\x00" in repo[k]
                for k in ("base", "target")
            ) or not isinstance(repo["include_untracked"], bool):
                raise ValueError(
                    "Base and target must be refs; include_untracked must be boolean"
                )
        if not isinstance(config.get("contracts", []), list):
            raise ValueError("Contracts must be a list")
        ids = set()
        for c in config.setdefault("contracts", []):
            if (
                not isinstance(c, dict)
                or any(
                    not isinstance(c.get(k), str) or not c[k].strip()
                    for k in ("id", "title", "expectation")
                )
                or c["id"] in ids
            ):
                raise ValueError("Contracts require unique IDs, titles and expectation")
            ids.add(c["id"])
            for role in ("producer", "consumer"):
                side = c.get(role)
                # An explicitly named external alias is a declared unavailable counterpart,
                # not a checkout to scan. Configured checkout failures still abort capture.
                if (
                    not isinstance(side, dict)
                    or not isinstance(side.get("repo"), str)
                    or not re.fullmatch(
                        r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", side["repo"]
                    )
                    or not isinstance(side.get("path"), str)
                    or not side["path"]
                    or "\x00" in side["path"]
                    or Path(side["path"]).is_absolute()
                    or ".." in Path(side["path"]).parts
                ):
                    raise ValueError(
                        "Contract sides require safe repository aliases and relative paths"
                    )
        config.setdefault("criteria", [])
        return config

    def _capture(self, config):
        from .inventory import capture_repo

        inventories = []
        for repo in config["repos"]:
            options = copy.deepcopy(repo)
            options["context_paths"] = sorted(
                {
                    c[side]["path"]
                    for c in config.get("contracts", [])
                    for side in ("producer", "consumer")
                    if c[side]["repo"] == repo["alias"]
                }
            )
            inventories.append(capture_repo(options))
        return inventories

    def list_sessions(self):
        with self._connect() as db:
            rows = db.execute(
                "SELECT id,json_extract(view,'$.title'),COALESCE(json_extract(view,'$.events[#-1].time'),json_extract(view,'$.created_at')) FROM sessions ORDER BY 3 DESC"
            )
            return [
                {"id": row[0], "title": row[1], "updated_at": row[2]} for row in rows
            ]

    def revision(self, session_id):
        with self._connect() as db:
            row = db.execute(
                "SELECT json_extract(view,'$.version'),json_extract(view,'$.capture') FROM sessions WHERE id=?",
                (session_id,),
            ).fetchone()
            if row is None:
                raise KeyError("Unknown review: " + str(session_id))
            return {"version": row[0], "capture": row[1]}

    def delete(self, session_id, expected_version):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT json_extract(view,'$.version') FROM sessions WHERE id=?",
                (session_id,),
            ).fetchone()
            if row is None:
                raise KeyError("Unknown review: " + str(session_id))
            if row[0] != expected_version:
                raise Conflict(
                    "Review changed; reload before deleting retained review data"
                )
            for table in ("captures", "events", "actions"):
                db.execute("DELETE FROM " + table + " WHERE session=?", (session_id,))
            db.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        return {"deleted": session_id}

    def create(self, config):
        config = self._config(config)
        repositories = self._capture(config)
        view = dict(
            id=uuid.uuid4().hex,
            title=config["title"],
            objective=config["objective"],
            config=config,
            version=1,
            capture=uuid.uuid4().hex,
            created_at=now(),
            repositories=repositories,
            units=analyze(config, repositories),
            events=[],
        )
        view["suggested_contracts"] = suggest_contracts(config, repositories)
        view["checks"] = []
        view["analysis_passes"] = {}
        view["analysis"] = {
            "mode": "offline",
            "status": "bounded checks complete",
            "tests": "not run",
            "limitations": [
                "Scope mapping and semantic minimalism require human inspection.",
                "Only frozen additions are checked for response field mismatches.",
            ],
        }
        with self._connect() as db:
            self._event(
                db,
                view,
                "create",
                reason="Objective and scope confirmed; complete capture recorded.",
            )
            self._save(db, view)
        return view

    def get(self, session_id, capture_id=None):
        with self._connect() as db:
            return self._read(db, session_id, capture_id)

    def refresh(self, session_id, expected_version, _config=None):
        old = self.get(session_id)
        if old["version"] != expected_version:
            raise Conflict("Review changed; reload before refreshing")
        config = _config or old["config"]
        repositories = self._capture(config)
        view = copy.deepcopy(old)
        view.update(config=config, title=config["title"], objective=config["objective"])
        view.update(
            capture=uuid.uuid4().hex,
            version=old["version"] + 1,
            repositories=repositories,
            units=analyze(config, repositories),
        )
        view["suggested_contracts"] = suggest_contracts(config, repositories)
        view["checks"] = []
        view["analysis_passes"] = {}
        prior = {u["id"]: u for u in old["units"]}
        changes = []
        for u in view["units"]:
            previous = prior.get(u["id"])
            if previous and dependency_fingerprint(
                previous, old["config"], old["repositories"]
            ) == dependency_fingerprint(u, view["config"], repositories):
                for key in ("status", "reason", "approval", "scope", "findings"):
                    if key in previous:
                        u[key] = copy.deepcopy(previous[key])
                dispositions = {
                    f["id"]: f.get("disposition") for f in previous["findings"]
                }
                for f in u["findings"]:
                    if f.get("pass_name"):
                        f.setdefault("origin_capture", f.get("capture", old["capture"]))
                        f["capture"] = view["capture"]
                    if dispositions.get(f["id"]):
                        f["disposition"] = dispositions[f["id"]]
                changes.append(
                    (u["id"], "carry", "Evidence and dependency bases unchanged.")
                )
            elif previous and (
                previous["status"] != "pending"
                or any(f.get("disposition") for f in previous["findings"])
            ):
                u["status"] = "stale"
                u["reason"] = (
                    "Relevant file, contract edge or repository base changed; inspect the new capture."
                )
                changes.append((u["id"], "stale", u["reason"]))
            if previous and dependency_fingerprint(
                previous, old["config"], old["repositories"]
            ) != dependency_fingerprint(u, view["config"], repositories):
                for finding in previous["findings"]:
                    if finding.get("pass_name") and finding["blocking"]:
                        carried = copy.deepcopy(finding)
                        carried.setdefault(
                            "origin_capture", finding.get("capture", old["capture"])
                        )
                        carried.update(
                            id="f-" + digest([finding["id"], view["capture"]])[:16],
                            evidence=u["atom_ids"],
                            capture=view["capture"],
                        )
                        carried.pop("disposition", None)
                        prefix = "Prior analysis needs reevaluation against changed evidence. "
                        carried["detail"] = prefix + finding["detail"].removeprefix(
                            prefix
                        )
                        u["findings"].append(carried)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if self._read(db, session_id)["version"] != expected_version:
                raise Conflict("Review changed during capture; reload and retry")
            self._event(
                db,
                view,
                "refresh",
                reason="All repository captures published atomically.",
            )
            for uid, action, reason in changes:
                self._event(
                    db, view, action, uid, reason, previous_capture=old["capture"]
                )
            self._save(db, view)
        return view

    def update_config(self, session_id, config, expected_version):
        return self.refresh(session_id, expected_version, _config=self._config(config))

    def decide(self, session_id, payload):
        required = ("unit_id", "action", "version", "capture", "action_id")
        if (
            not isinstance(payload, dict)
            or any(k not in payload for k in required)
            or not payload["action_id"]
        ):
            raise ValueError(
                "Decision requires unit, action, version, capture and unique action_id"
            )
        if any(
            not isinstance(payload[k], str)
            for k in ("unit_id", "action", "capture", "action_id")
        ) or not isinstance(payload["version"], int):
            raise ValueError(
                "Decision IDs and action must be strings; version must be an integer"
            )
        action = payload["action"]
        if action not in ("approve", "request_changes", "defer", "dismiss"):
            raise ValueError("Unsupported decision action")
        reason = str(payload.get("reason", "")).strip()
        if action != "approve" and not reason:
            raise ValueError("A reason is required for this decision")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT payload FROM actions WHERE session=? AND id=?",
                (session_id, str(payload["action_id"])),
            ).fetchone()
            if existing:
                if json.loads(existing[0]) != payload:
                    raise Conflict(
                        "action_id was already used for a different decision"
                    )
                return self._read(db, session_id)
            view = self._read(db, session_id)
            if (
                payload["version"] != view["version"]
                or payload["capture"] != view["capture"]
            ):
                raise Conflict(
                    "Review or capture changed; reload before recording a decision"
                )
            unit = next(
                (u for u in view["units"] if u["id"] == payload["unit_id"]), None
            )
            if unit is None:
                raise KeyError("Unknown unit")
            if action == "dismiss":
                finding = next(
                    (
                        f
                        for f in unit["findings"]
                        if f["id"] == payload.get("finding_id")
                    ),
                    None,
                )
                if finding is None:
                    raise KeyError("Unknown finding")
                finding["disposition"] = {
                    "action": "dismissed",
                    "reason": reason,
                    "capture": view["capture"],
                    "time": now(),
                    "evidence": finding["evidence"],
                }
            else:
                unit["status"] = {
                    "approve": "approved",
                    "request_changes": "changes_requested",
                    "defer": "deferred",
                }[action]
                unit["reason"] = reason
                if action == "approve":
                    unit["approval"] = {
                        "capture": view["capture"],
                        "time": now(),
                        "action_id": payload["action_id"],
                    }
                    unit.setdefault(
                        "scope",
                        {
                            "evidence": unit["atom_ids"],
                            "criteria": view["config"].get("criteria", []),
                        },
                    )["classification"] = "human_confirmed"
            view["version"] += 1
            self._event(
                db,
                view,
                action,
                unit["id"],
                reason,
                action_id=payload["action_id"],
                finding_id=payload.get("finding_id"),
                atom_ids=unit["atom_ids"],
            )
            db.execute(
                "INSERT INTO actions VALUES (?,?,?)",
                (session_id, str(payload["action_id"]), json.dumps(payload)),
            )
            self._save(db, view)
        return view

    @staticmethod
    def _test_status(view):
        checks = [c for c in view.get("checks", []) if c["capture"] == view["capture"]]
        if not checks:
            return "not run"
        return "recorded checks: " + ", ".join(
            c["name"] + (" passed" if c["passed"] else " failed") for c in checks
        )

    @staticmethod
    def _counts(view):
        view.setdefault(
            "analysis",
            {
                "mode": "offline",
                "limitations": [
                    "Semantic scope and minimalism require human inspection."
                ],
            },
        )["tests"] = Engine._test_status(view)
        files = [f for r in view["repositories"] for f in r["files"]]
        atoms = {a["id"] for f in files for a in f["atoms"]}
        approved = {
            a for u in view["units"] if u["status"] == "approved" for a in u["atom_ids"]
        } & atoms
        represented = {a for u in view["units"] for a in u["atom_ids"]} & atoms
        classified = {
            a
            for u in view["units"]
            if u.get("scope", {}).get("classification") == "human_confirmed"
            for a in u["atom_ids"]
        } & atoms
        view["counts"] = {
            "files": len(files),
            "atoms": len(atoms),
            "approved": len(approved),
            "units": len(view["units"]),
            "represented": len(represented),
            "classified": len(classified),
        }
        view["coverage"] = {
            "inventory": {"represented": len(represented), "total": len(atoms)},
            "analysis": {
                "status": "bounded offline checks; semantic assessment remains manual",
                "tests": "not run"
                if not view.get("checks")
                else "see capture-bound check evidence",
                "passes": {
                    name: dict(
                        record,
                        completed=len(
                            set(record.get("assessed", []))
                            | set(record.get("unknown", []))
                        ),
                        total=len(atoms),
                        pending=len(
                            atoms
                            - set(record.get("assessed", []))
                            - set(record.get("unknown", []))
                        ),
                    )
                    for name, record in view.get("analysis_passes", {}).items()
                },
            },
            "classification": {
                "confirmed": len(classified),
                "unknown": len(atoms - classified),
                "total": len(atoms),
            },
            "human_approval": {"approved": len(approved), "total": len(atoms)},
            "empty_reason": "No changed atoms; approval is not applicable."
            if not atoms
            else None,
        }

    def verify(self, session_id):
        view = self.get(session_id)
        blockers = []
        all_atoms = {
            a["id"]
            for r in view["repositories"]
            for f in r["files"]
            for a in f["atoms"]
        }
        represented = {a for u in view["units"] for a in u["atom_ids"]}
        if all_atoms - represented:
            blockers.append(
                "Inventory atoms have no review unit; restore complete grouping."
            )
        if represented - all_atoms:
            blockers.append("Review references evidence outside the frozen inventory.")
        for repo in view["repositories"]:
            actual_files = len(repo["files"])
            actual_atoms = sum(len(f["atoms"]) for f in repo["files"])
            raw = repo.get("raw_counts", {})
            if raw and (
                raw.get("files") != actual_files or raw.get("atoms") != actual_atoms
            ):
                blockers.append(
                    repo["alias"]
                    + ": Git inventory counts disagree with frozen records; recapture."
                )
            reconciliation = repo.get("reconciliation", {})
            if reconciliation and not all(
                reconciliation.get(k) for k in ("manifest", "canonical_patch")
            ):
                blockers.append(
                    repo["alias"] + ": incomplete Git reconciliation; recapture."
                )
        for u in view["units"]:
            for finding in u["findings"]:
                if not set(finding["evidence"]) <= set(u["atom_ids"]):
                    blockers.append(
                        u["title"]
                        + ": finding references invalid evidence; restore capture integrity."
                    )
            if u["status"] != "approved":
                blockers.append(
                    u["title"]
                    + ": "
                    + u["status"]
                    + "; inspect and explicitly approve."
                )
            for f in u["findings"]:
                if f["blocking"] and not f.get("disposition"):
                    blockers.append(
                        u["title"]
                        + ": "
                        + f["title"]
                        + "; fix and refresh, or dismiss with an evidence-based reason."
                    )
        for name in view["config"].get("required_checks", []):
            check = next(
                (
                    c
                    for c in reversed(view.get("checks", []))
                    if c["name"] == name and c["capture"] == view["capture"]
                ),
                None,
            )
            if not check or not check["passed"]:
                blockers.append(
                    "Required check "
                    + name
                    + " lacks current passing execution evidence."
                )
        for name in view["config"].get("required_passes", []):
            attempt = view.get("analysis_passes", {}).get(name, {})
            if (
                all_atoms - set(attempt.get("assessed", []))
                or attempt.get("unknown")
                or not attempt
            ):
                blockers.append(
                    "Required analysis pass "
                    + name
                    + " is incomplete or has unresolved unknowns."
                )
        try:
            live = self._capture(view["config"])
            if self._inventory_identity(live) != self._inventory_identity(
                view["repositories"]
            ):
                blockers.append(
                    "Live Git inputs differ from this capture; refresh before sign-off."
                )
        except (ValueError, OSError) as exc:
            blockers.append("Cannot verify live Git inputs: " + str(exc))
        latest = self.get(session_id)
        if latest["version"] != view["version"]:
            blockers.append("Review changed during verification; retry.")
        return {
            "ready": not blockers,
            "blockers": blockers,
            "capture": view["capture"],
            "version": view["version"],
            "counts": view["counts"],
            "tests": self._test_status(view),
        }

    @staticmethod
    def _inventory_identity(repositories):
        return digest(
            [
                {
                    k: r.get(k)
                    for k in ("alias", "base_sha", "target_id", "files", "contexts")
                }
                for r in repositories
            ]
        )

    def record_analysis(self, session_id, payload):
        """Import an explicitly requested, evidence-validated batch; never approve atoms."""
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("pass_name"), str)
            or not payload["pass_name"].strip()
        ):
            raise ValueError("An analysis pass_name is required")
        for field in ("assessed", "unknown"):
            if not isinstance(payload.get(field, []), list) or not all(
                isinstance(a, str) for a in payload.get(field, [])
            ):
                raise ValueError(field + " must be a list of frozen atom IDs")
        if not isinstance(payload.get("findings", []), list) or not all(
            isinstance(f, dict) for f in payload.get("findings", [])
        ):
            raise ValueError("Findings must be a list of objects")
        if not isinstance(payload.get("provenance", ""), str):
            raise ValueError("Provenance must be text")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            view = self._read(db, session_id)
            self._expected(view, payload)
            atoms = {
                a["id"]
                for r in view["repositories"]
                for f in r["files"]
                for a in f["atoms"]
            }
            assessed, unknown = (
                set(payload.get("assessed", [])),
                set(payload.get("unknown", [])),
            )
            if (assessed | unknown) - atoms or assessed & unknown:
                raise ValueError(
                    "Analysis outcomes must use distinct valid frozen atom IDs"
                )
            units = {u["id"]: u for u in view["units"]}
            findings = []
            for supplied in payload.get("findings", []):
                if not isinstance(supplied.get("unit_id"), str):
                    raise ValueError("Finding unit_id must be a string")
                u = units.get(supplied["unit_id"])
                evidence = supplied.get("evidence", [])
                if (
                    not isinstance(evidence, list)
                    or not all(isinstance(a, str) for a in evidence)
                    or not u
                    or not evidence
                    or not set(evidence) <= set(u["atom_ids"])
                ):
                    raise ValueError(
                        "Finding evidence must belong to its current captured unit"
                    )
                if any(
                    not isinstance(supplied.get(k), str) or not supplied[k].strip()
                    for k in ("title", "detail")
                ) or not isinstance(supplied.get("blocking"), bool):
                    raise ValueError(
                        "Findings require title, detail and boolean blocking"
                    )
                f = {
                    k: supplied[k] for k in ("title", "detail", "blocking", "evidence")
                }
                f.update(
                    id="f-" + digest([payload["pass_name"], supplied])[:16],
                    pass_name=payload["pass_name"],
                    capture=view["capture"],
                    provenance=payload.get("provenance", "human-reviewed import"),
                )
                findings.append((u, f))
            name = payload["pass_name"]
            prior = view.setdefault("analysis_passes", {}).get(name, {})
            # Repeat batches replace identical findings and merge disjoint assessed work.
            for u, f in findings:
                existing = next(
                    (item for item in u["findings"] if item["id"] == f["id"]), None
                )
                if not existing:
                    u["findings"].append(f)
            old_assessed = set(prior.get("assessed", [])) - unknown
            old_unknown = set(prior.get("unknown", [])) - assessed
            view["analysis_passes"][name] = dict(
                capture=view["capture"],
                assessed=sorted(old_assessed | assessed),
                unknown=sorted(old_unknown | unknown),
                provenance=payload.get("provenance", "human-reviewed import"),
            )
            view["version"] += 1
            self._event(
                db,
                view,
                "analysis",
                reason="Recorded evidence-validated analysis: " + name,
            )
            self._save(db, view)
        return view

    @staticmethod
    def _expected(view, payload):
        if (
            payload.get("capture") != view["capture"]
            or payload.get("version") != view["version"]
        ):
            raise Conflict(
                "Review or capture changed; reload before recording evidence"
            )

    def record_check(self, session_id, payload):
        """Record trusted runner output. The transport must obtain execution consent."""
        command = payload.get("command")
        valid_command = (isinstance(command, str) and bool(command.strip())) or (
            isinstance(command, list)
            and bool(command)
            and all(isinstance(arg, str) and "\x00" not in arg for arg in command)
            and bool(command[0])
        )
        if (
            not isinstance(payload.get("name"), str)
            or not payload["name"].strip()
            or not valid_command
            or not isinstance(payload.get("passed"), bool)
            or not isinstance(payload.get("output", ""), str)
        ):
            raise ValueError("Check requires name, command and boolean passed")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            view = self._read(db, session_id)
            self._expected(view, payload)
            check = {
                k: payload.get(k, "")
                for k in ("name", "passed", "command", "output", "repo", "exit_code")
            }
            if check["repo"] and check["repo"] not in {
                r["alias"] for r in view["repositories"]
            }:
                raise ValueError("Check repository is outside this capture")
            check.update(
                capture=view["capture"],
                time=now(),
                provenance="explicit trusted runner",
            )
            view.setdefault("checks", []).append(check)
            view["version"] += 1
            self._event(
                db, view, "check", reason="Recorded check execution: " + payload["name"]
            )
            self._save(db, view)
        return view

    def history(self, session_id):
        with self._connect() as db:
            self._read(db, session_id)
            return [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT payload FROM events WHERE session=? ORDER BY seq",
                    (session_id,),
                )
            ]

    def export(self, session_id, format):
        if format not in ("json", "markdown"):
            raise ValueError("Export format must be markdown or json")
        view = self.get(session_id)
        verification = self.verify(session_id)
        if (
            verification["capture"] != view["capture"]
            or verification["version"] != view["version"]
        ):
            verification["ready"] = False
            verification["blockers"].append(
                "Review changed during export; regenerate the handoff."
            )
        portable = copy.deepcopy(view)
        roots = []
        for repo in portable["config"]["repos"]:
            roots.append(repo.pop("path"))
        # Repository records can contain full frozen blobs; portable evidence uses patches only.
        allowed_repo = (
            "alias",
            "base_sha",
            "target_id",
            "files",
            "counts",
            "integrity",
        )
        portable["repositories"] = [
            {k: v for k, v in r.items() if k in allowed_repo}
            for r in portable["repositories"]
        ]
        for r in portable["repositories"]:
            for f in r["files"]:
                visible = eligible(f["path"]) and (
                    not f.get("old_path") or eligible(f["old_path"])
                )
                for record in [f, *f["atoms"]]:
                    if "patch" in record:
                        record["patch"] = (
                            redact(record["patch"])
                            if visible
                            else "[sensitive file content omitted]"
                        )
                for key in list(f):
                    if key in (
                        "old_text",
                        "new_text",
                        "old_content",
                        "new_content",
                        "content",
                        "before",
                        "after",
                        "blob",
                        "blobs",
                        "full_text",
                    ):
                        del f[key]
        for unit in portable["units"]:
            for side in unit.get("sides", {}).values():
                for ctx in side.get("contexts", []):
                    ctx.pop("text", None)
        for checked in portable.get("checks", []):
            checked["output"] = redact(checked.get("output", ""))
        if format == "json":
            result = json.dumps(
                {
                    "schema_version": 1,
                    "review": portable,
                    "verification": verification,
                    "redacted_fields": [
                        "config.repos.path",
                        "full frozen blob contents",
                        "sensitive file patches and detected secret lines",
                    ],
                    "limitations": view["analysis"]["limitations"],
                },
                indent=2,
                ensure_ascii=True,
            )
        else:
            c = view["counts"]
            lines = [
                "# " + view["title"],
                "",
                view["objective"],
                "",
                "Capture: `" + view["capture"] + "` · version " + str(view["version"]),
                "",
                "**"
                + (
                    "Ready for human PR handoff"
                    if verification["ready"]
                    else "Incomplete review"
                )
                + "**",
                "",
                "Coverage: %s/%s atoms inventoried in units; %s/%s explicitly approved; %s/%s scope confirmed."
                % (
                    c["represented"],
                    c["atoms"],
                    c["approved"],
                    c["atoms"],
                    c["classified"],
                    c["atoms"],
                ),
                "",
                "Analysis: bounded offline checks. Semantic scope/minimalism require human inspection. Tests: "
                + self._test_status(view)
                + ".",
                "",
                "## Blockers",
                "",
            ]
            lines += ["- " + b for b in verification["blockers"]] or ["None."]
            lines += ["", "## Decisions", ""]
            for u in view["units"]:
                lines += [
                    "- **"
                    + u["title"]
                    + "** — "
                    + u["status"]
                    + (": " + u["reason"] if u["reason"] else "")
                    + " (unit `"
                    + u["id"]
                    + "`; atoms "
                    + ", ".join("`" + a + "`" for a in u["atom_ids"])
                    + ")"
                ]
                for f in u["findings"]:
                    lines += [
                        "  - "
                        + f["title"]
                        + ": "
                        + f["detail"]
                        + (
                            " Dismissed: " + f["disposition"]["reason"]
                            if f.get("disposition")
                            else ""
                        )
                    ]
            lines += ["", "## Repository snapshots", ""]
            lines += [
                "- "
                + r["alias"]
                + ": base `"
                + r["base_sha"]
                + "`, target `"
                + r["target_id"]
                + "`"
                for r in view["repositories"]
            ]
            lines += ["", "## Check evidence", ""]
            lines += [
                "- "
                + c["name"]
                + ": "
                + ("passed" if c["passed"] else "failed")
                + " at `"
                + c["capture"]
                + "` via explicitly trusted command `"
                + (
                    c["command"]
                    if isinstance(c["command"], str)
                    else " ".join(c["command"])
                )
                + "`."
                for c in view.get("checks", [])
            ] or ["No trusted checks recorded."]
            result = "\n".join(lines) + "\n"
        for root in sorted(roots, key=len, reverse=True):
            result = result.replace(root, "[local repository]")
        return result
