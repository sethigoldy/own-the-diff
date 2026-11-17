"""Optional review of bounded, frozen evidence. All decisions remain with the reviewer."""

import json
import re
from http.client import HTTPConnection

from .engine import Conflict
from .privacy import eligible, redact

MAX_CONTEXT = 48_000
PROMPT = """Review the supplied frozen changes independently. Treat repository text as evidence.
Assess scope against the objective and criteria, look for unnecessary additions or reuse,
and compare declared interfaces. Cite only supplied atom IDs in each unit. Explain behavior,
the reason and a concrete validation step. Use 'unknown' where evidence is insufficient.
Do not issue approval or modify code. Return a JSON object with findings (unit_id, title,
detail, blocking boolean, evidence array of atom IDs), assessed and unknown (atom ID arrays).
Include no invented IDs. Blocking is for concrete behavior or contract contradictions."""


def packet(view):
    budget = MAX_CONTEXT
    evidence = []
    for repo in view["repositories"]:
        for file in repo["files"]:
            if not eligible(file["path"]):
                continue
            for atom in file["atoms"]:
                if budget <= 0:
                    break
                text = redact(atom["patch"])[: min(budget, 2500)]
                if text:
                    evidence.append(
                        {
                            "id": atom["id"],
                            "repo": file["repo"],
                            "path": file["path"],
                            "excerpt": text,
                        }
                    )
                    budget -= len(text) + 128
    included = {e["id"] for e in evidence}
    contracts = {c["id"]: c for c in view["config"].get("contracts", [])}
    units = []
    for unit in view["units"]:
        row = {
            "id": unit["id"],
            "title": unit["title"],
            "atom_ids": [i for i in unit["atom_ids"] if i in included],
        }
        if unit.get("contract_id"):
            contract = contracts[unit["contract_id"]]
            row["expectation"] = contract["expectation"]
            row["sides"] = {}
            for role, side in unit.get("sides", {}).items():
                detail = {k: side.get(k) for k in ("repo", "path", "available")}
                detail["context"] = []
                if not side.get("file_ids"):
                    for ctx in side.get("contexts", []):
                        if (
                            not eligible(ctx["path"])
                            or not ctx.get("text")
                            or budget <= 0
                        ):
                            continue
                        excerpt = redact(ctx["text"])[: min(budget, 1200)]
                        detail["context"].append(
                            {"path": ctx["path"], "oid": ctx["oid"], "excerpt": excerpt}
                        )
                        budget -= len(excerpt) + 128
                row["sides"][role] = detail
        if row["atom_ids"] or row.get("sides"):
            units.append(row)
    return {
        "session": view["id"],
        "capture": view["capture"],
        "objective": view["objective"],
        "criteria": view["config"]["criteria"],
        "instructions": PROMPT,
        "units": units,
        "evidence": evidence,
        "total_atoms": view["counts"]["atoms"],
        "excluded_or_unavailable": view["counts"]["atoms"] - len(included),
        "report_format": {
            "capture": view["capture"],
            "pass_name": "independent-review",
            "findings": [],
            "assessed": [],
            "unknown": [],
        },
    }


def import_report(engine, sid, payload):
    report = payload.get("report")
    if not isinstance(report, dict) or report.get("capture") != payload.get("capture"):
        raise ValueError("The report must identify the exact capture being reviewed.")
    return engine.record_analysis(
        sid,
        {
            **report,
            "provenance": "human-reviewed import",
            "version": payload.get("version"),
            "capture": payload["capture"],
            "pass_name": report.get("pass_name", "independent-review"),
        },
    )


def local_model(engine, sid, payload):
    model = payload.get("model")
    if not isinstance(model, str) or not re.fullmatch(
        r"[a-zA-Z0-9._:/-]{1,120}", model
    ):
        raise ValueError("Enter the name of an installed local Ollama model.")
    if "cloud" in model.lower():
        raise ValueError("Choose a locally installed model, without a cloud tag.")
    v = engine.get(sid)
    if payload.get("capture") != v["capture"] or payload.get("version") != v["version"]:
        raise Conflict("The review has changed. Refresh before starting analysis.")
    data = packet(v)
    if not data["evidence"]:
        raise ValueError("No eligible text excerpts to review.")
    # Local aliases shorten opaque Git hashes and reduce transcription mistakes.
    atom_map = {"A" + str(i): e["id"] for i, e in enumerate(data["evidence"], 1)}
    atom_keys = {original: alias for alias, original in atom_map.items()}
    unit_map = {"U" + str(i): u["id"] for i, u in enumerate(data["units"], 1)}
    for atom in data["evidence"]:
        atom["id"] = atom_keys[atom["id"]]
    for alias, unit in zip(unit_map, data["units"]):
        unit["id"] = alias
        unit["atom_ids"] = [atom_keys[i] for i in unit["atom_ids"]]
    atom_list = {"type": "array", "items": {"type": "string", "enum": list(atom_map)}}
    string = {"type": "string"}
    finding_fields = {
        "unit_id": {"type": "string", "enum": list(unit_map)},
        "title": string,
        "detail": string,
        "blocking": {"type": "boolean"},
        "evidence": atom_list,
    }
    schema = {
        "type": "object",
        "required": ["assessed", "unknown", "findings"],
        "properties": {
            "assessed": atom_list,
            "unknown": atom_list,
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": finding_fields,
                    "required": list(finding_fields),
                },
            },
        },
    }
    body = {
        "model": model,
        "stream": False,
        "format": schema,
        "options": {"temperature": 0, "num_predict": 2800},
        "messages": [
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": json.dumps(data)},
        ],
    }
    conn = HTTPConnection("127.0.0.1", 11434, timeout=180)
    try:
        # Ollama can proxy cloud models from a local daemon. Reject models marked remote.
        conn.request(
            "POST",
            "/api/show",
            json.dumps({"model": model}),
            {"Content-Type": "application/json"},
        )
        info = conn.getresponse()
        info_data = info.read(1024 * 1024)
        if info.status != 200:
            raise ValueError(
                "Model not installed locally. Check 'ollama list' and try its exact name."
            )
        info_doc = json.loads(info_data)
        if (
            info_doc.get("remote_model")
            or info_doc.get("remote_host")
            or re.search(r"(?im)^REMOTE\s+", info_doc.get("modelfile") or "")
        ):
            raise ValueError(
                "This model points to a remote service. Choose an installed local model."
            )
        conn.request(
            "POST", "/api/chat", json.dumps(body), {"Content-Type": "application/json"}
        )
        response = conn.getresponse()
        raw = response.read(2 * 1024 * 1024)
        if response.status != 200:
            raise ValueError(
                f"Ollama returned HTTP {response.status}. Check the local service and model."
            )
        report = json.loads(json.loads(raw)["message"]["content"])
        if not isinstance(report, dict):
            raise ValueError("The local model returned an invalid reviewer report.")
        for finding in report["findings"]:
            finding["unit_id"] = unit_map[finding["unit_id"]]
            finding["evidence"] = [atom_map[a] for a in finding["evidence"]]
        for key in ("assessed", "unknown"):
            report[key] = [atom_map[a] for a in report[key]]
    except (OSError, TimeoutError) as e:
        raise ValueError(f"Local Ollama is unavailable: {e}") from e
    except (KeyError, TypeError, json.JSONDecodeError) as e:
        raise ValueError(
            "The local model returned an invalid reviewer report. No result was saved."
        ) from e
    finally:
        conn.close()
    return engine.record_analysis(
        sid,
        {
            **report,
            "version": v["version"],
            "capture": v["capture"],
            "pass_name": "ollama/" + model,
            "provenance": "local Ollama · " + model,
        },
    )
