"""Bounded, deterministic offline review. Findings are questions, never test results."""

import fnmatch
import hashlib
import json
import re


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=True).encode()
    ).hexdigest()


def _matches(file, side):
    return file["repo"] == side["repo"] and (
        fnmatch.fnmatchcase(file["path"], side["path"])
        or fnmatch.fnmatchcase(file.get("old_path") or "", side["path"])
    )


def _added(files):
    return "\n".join(
        line[1:]
        for f in files
        for atom in f["atoms"]
        for line in atom["patch"].splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )


def analyze(config, repositories):
    files = [f for repo in repositories for f in repo["files"]]
    units, covered = [], set()

    def unit(key, title, selected, contract=None):
        atoms = sorted({a["id"] for f in selected for a in f["atoms"]})
        return {
            "id": "u-" + digest(key)[:16],
            "title": title,
            "summary": contract["expectation"]
            if contract
            else "Inspect the complete frozen change and map it to the agreed objective.",
            "risk": "high" if contract else "medium",
            "status": "pending",
            "reason": "",
            "atom_ids": atoms,
            "file_ids": sorted({f["id"] for f in selected}),
            "repos": sorted(
                {f["repo"] for f in selected}
                | (
                    {contract["producer"]["repo"], contract["consumer"]["repo"]}
                    if contract
                    else set()
                )
            ),
            "contract_id": contract["id"] if contract else None,
            "findings": [],
            "scope": {
                "classification": "unknown",
                "basis": "Human approval must confirm this change serves the recorded objective.",
                "criteria": config.get("criteria", []),
                "evidence": atoms,
            },
            "minimalism": {
                "status": "unassessed",
                "detail": "No semantic equivalence or removal claim established. Inspect callers and existing alternatives before removing code.",
                "evidence": atoms,
            },
        }

    def finding(u, key, title, detail, blocking):
        u["findings"].append(
            {
                "id": "f-" + digest([u["id"], key])[:16],
                "title": title,
                "detail": detail,
                "blocking": blocking,
                "evidence": u["atom_ids"][:],
            }
        )

    for c in config.get("contracts", []):
        producer = [f for f in files if _matches(f, c["producer"])]
        consumer = [f for f in files if _matches(f, c["consumer"])]
        contexts = {
            role: [
                dict(ctx, repo=r["alias"])
                for r in repositories
                for ctx in r.get("contexts", [])
                if r["alias"] == c[role]["repo"]
                and fnmatch.fnmatchcase(ctx["path"], c[role]["path"])
            ]
            for role in ("producer", "consumer")
        }
        selected = list({f["id"]: f for f in producer + consumer}.values())
        u = unit(["contract", c["id"]], c["title"], selected, c)
        u["sides"] = {
            role: {
                "repo": c[role]["repo"],
                "path": c[role]["path"],
                "file_ids": [f["id"] for f in selected if _matches(f, c[role])],
                "contexts": contexts[role],
                "available": bool(
                    (producer if role == "producer" else consumer) or contexts[role]
                ),
            }
            for role in ("producer", "consumer")
        }
        for role, matches in [("producer", producer), ("consumer", consumer)]:
            if not matches and not contexts[role]:
                finding(
                    u,
                    ["missing", role],
                    "Missing " + role + " evidence",
                    "No changed evidence matches %s:%s. Supply counterpart evidence or dismiss with a reason documenting your inspection."
                    % (c[role]["repo"], c[role]["path"]),
                    True,
                )
        p = (
            _added(producer)
            + "\n"
            + "\n".join(ctx.get("text") or "" for ctx in contexts["producer"])
        )
        q = (
            _added(consumer)
            + "\n"
            + "\n".join(ctx.get("text") or "" for ctx in contexts["consumer"])
        )
        for snake in sorted(
            set(re.findall(r"""["']([a-z][a-z0-9]*_[a-z0-9_]+)["']\s*:""", p))
        ):
            camel = re.sub(r"_([a-z])", lambda m: m[1].upper(), snake)
            if re.search(r"\." + re.escape(camel) + r"\b", q):
                finding(
                    u,
                    ["field", snake, camel],
                    "Response field mismatch: " + snake + " / " + camel,
                    "Producer additions return `%s`; consumer additions read `.%s`. Unless an adapter converts the field, a successful response yields an undefined identifier. Align the field or document the adapter; validate a response fixture across both sides."
                    % (snake, camel),
                    True,
                )
        covered.update(u["file_ids"])
        units.append(u)
    for f in files:
        if f["id"] not in covered:
            u = unit(["file", f["repo"], f["path"]], f["repo"] + ": " + f["path"], [f])
            parts = f["path"].lower().split("/")
            test_path = (
                any(part in ("test", "tests", "__tests__") for part in parts)
                or parts[-1].startswith("test_")
                or bool(re.search(r"\.(test|spec)\.", parts[-1]))
            )
            mechanical = any(
                part in ("generated", "vendor", "node_modules", "dist")
                for part in parts
            ) or parts[-1] in (
                "package-lock.json",
                "yarn.lock",
                "pnpm-lock.yaml",
                "poetry.lock",
            )
            if test_path or mechanical:
                u["risk"] = "low"
                u["risk_basis"] = (
                    "Test-path signal; inspect assertions and execution coverage."
                    if test_path
                    else "Generated/vendor/lockfile path signal; inspect source and dependency impact."
                )
            else:
                u["risk_basis"] = "Ordinary changed file; semantic risk is unassessed."
            words = set(re.findall(r"[a-z]{4,}", f["path"].lower()))
            candidates = [
                criterion
                for criterion in config.get("criteria", [])
                if words & set(re.findall(r"[a-z]{4,}", criterion.lower()))
            ]
            if candidates:
                u["scope"]["candidates"] = candidates
                u["scope"]["basis"] = (
                    "Path words overlap these criteria; this is a navigation hint, not a semantic mapping. Human confirmation is required."
                )
            units.append(u)
    for u in units:
        selected = [f for f in files if f["id"] in u["file_ids"]]
        if re.search(r"\bclass\s+\w*Store\b|\bnew\s+\w*Client\s*\(", _added(selected)):
            finding(
                u,
                "reuse",
                "Check whether the new persistence wrapper is needed",
                "A new store or client appears in the cited additions. No equivalent existing implementation is established. Inspect callers, transaction scope and credentials; compare an existing client before recommending removal.",
                False,
            )
    return sorted(
        units,
        key=lambda u: (
            {"high": 0, "medium": 1, "low": 2}[u["risk"]],
            u["title"],
            u["id"],
        ),
    )


def dependency_fingerprint(unit, config, repositories):
    files = [f for r in repositories for f in r["files"] if f["id"] in unit["file_ids"]]
    repos = [r for r in repositories if r["alias"] in unit["repos"]]
    context = [u for u in unit.get("sides", {}).values()]
    return digest(
        {
            "files": files,
            "contexts": context,
            "bases": [(r["alias"], r["base_sha"]) for r in repos],
            "contract": config.get("contracts", []),
            "objective": config["objective"],
            "criteria": config.get("criteria", []),
            "configuration": config,
        }
    )


def suggest_contracts(config, repositories):
    """Advisory literal route matches; no source reads and no automatic scope edits."""
    producers, consumers = {}, {}
    methods = "get|post|put|patch|delete|head|options"
    # Keep offsets while excluding comments and string contents from call discovery.
    tokens = re.compile(
        r'''/\*[\s\S]*?\*/|//[^\n]*|\#[^\n]*|"""[\s\S]*?"""|\x27\x27\x27[\s\S]*?\x27\x27\x27|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`'''
    )
    literal = re.compile(r"""\s*(["'`])([^\n]*?)\1""")

    def normalized(path):
        if (
            not path.startswith("/")
            or "?" in path
            or "#" in path
            or "\\" in path
            or "//" in path
        ):
            return None
        count = 0
        parts = []
        for part in path.split("/"):
            if re.fullmatch(r"\{[A-Za-z_]\w*\}|:[A-Za-z_]\w*|\$\{[A-Za-z_]\w*\}", part):
                count += 1
                parts.append("{param}")
            elif any(ch in part for ch in "{}$:*"):
                return None
            else:
                parts.append(part)
        return "/".join(parts) if count <= 1 else None

    files = [f for repo in repositories for f in repo["files"]]
    for f in files[:200]:
        text = f.get("new_text")
        if (
            not isinstance(text, str)
            or len(text) > 262144
            or not f["path"].endswith((".py", ".js", ".jsx", ".ts", ".tsx"))
        ):
            continue
        masked = tokens.sub(lambda m: re.sub(r"[^\n]", " ", m[0]), text)
        patterns = [
            (producers, re.compile(r"(?m)^\s*@\w+\.(" + methods + r"|route)\s*\(")),
            (
                producers,
                re.compile(r"(?m)^\s*(?:app|router|server)\.(" + methods + r")\s*\("),
            ),
            (consumers, re.compile(r"\bfetch\s*\(")),
        ]
        for bucket, pattern in patterns:
            for call in list(pattern.finditer(masked))[:100]:
                rest = text[call.end() : call.end() + 1024]
                value = literal.match(rest)
                if not value:
                    continue
                path = value[2]
                key_path = normalized(path)
                if key_path is None:
                    continue
                suffix = rest[value.end() :]
                if bucket is consumers:
                    # Accept only a closed simple options literal, or a URL-only call.
                    options = re.match(r"\s*,\s*\{([^{}]{0,500})\}\s*\)", suffix)
                    if options:
                        method_match = re.search(
                            r"""\bmethod\s*:\s*['"](GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)['"]""",
                            options[1],
                            re.I,
                        )
                        if re.search(r"\bmethod\s*:", options[1]) and not method_match:
                            continue
                        method = method_match[1].upper() if method_match else "GET"
                    elif re.match(r"\s*\)", suffix):
                        method = "GET"
                    else:
                        continue
                else:
                    method = call[1].upper()
                    if method == "ROUTE":
                        route_methods = re.match(
                            r"""\s*,\s*methods\s*=\s*\[\s*['"](GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)['"]\s*\]\s*\)""",
                            suffix,
                            re.I,
                        )
                        if not route_methods:
                            continue
                        method = route_methods[1].upper()
                offset = call.start() + len(call[0]) - len(call[0].lstrip())
                line = text.count("\n", 0, offset) + 1
                evidence = dict(
                    repo=f["repo"],
                    path=f["path"],
                    line=line,
                    excerpt=text.splitlines()[line - 1].strip()[:300],
                    file_id=f["id"],
                )
                bucket.setdefault((method, key_path), []).append(evidence)
    suggestions = []
    for key in sorted(producers.keys() & consumers.keys()):
        p, c = producers[key], consumers[key]
        if len(p) != 1 or len(c) != 1 or p[0]["repo"] == c[0]["repo"]:
            continue
        producer, consumer = p[0], c[0]
        if any(
            _matches(producer, contract["producer"])
            and _matches(consumer, contract["consumer"])
            for contract in config.get("contracts", [])
        ):
            continue
        method, path = key
        suggestions.append(
            dict(
                id="inferred-" + digest([key, producer, consumer])[:16],
                title=method + " " + path,
                producer={k: producer[k] for k in ("repo", "path")},
                consumer={k: consumer[k] for k in ("repo", "path")},
                expectation="Confirm that the consumer of %s %s uses the producer response correctly."
                % key,
                basis="One literal producer route and one fetch call share an HTTP method and path across repositories. At most one complete path-parameter segment is normalized. Routing prefixes, adapters and runtime behavior are not established.",
                evidence=[
                    dict(producer, role="producer"),
                    dict(consumer, role="consumer"),
                ],
                provenance="inferred",
            )
        )
    return suggestions[:50]
