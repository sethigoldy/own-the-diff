"""Terminal entry points for the local review workspace."""

import argparse
import json
import os
from pathlib import Path
import sys
import uuid
from urllib.parse import quote

from .assistance import import_report, local_model, packet
from .demo import demo
from .engine import Engine


def parser():
    p = argparse.ArgumentParser(
        prog="cor", description="Review and own changes across local Git repositories."
    )
    p.add_argument(
        "--home",
        help="Private workspace directory (default: COR_HOME or your user data directory).",
    )
    p.add_argument("--version", action="version", version="Code Ownership Review 0.1.0")
    cmds = p.add_subparsers(dest="cmd", required=True)
    commands = {
        "init": "Create a review and capture its Git changes.",
        "list": "List locally saved reviews.",
        "demo": "Open or create a real, editable two-repository example.",
        "capture": "Freeze a new capture and reconcile decisions.",
        "status": "Show reviewed and outstanding work.",
        "inventory": "Inspect every frozen file, hunk and metadata change.",
        "analyze": "Inspect offline findings, run a local model or import a reviewer report.",
        "review": "Inspect evidence and record an explicit decision.",
        "history": "Show the decision and capture history.",
        "verify": "Compare with live Git and check readiness.",
        "export": "Export a Markdown summary or JSON ledger.",
        "delete": "Remove a review and its history; leave Git folders untouched.",
        "web": "Serve the browser application on loopback.",
        "check": "Run a trusted test on a copy of the frozen workspace.",
    }
    for name, desc in commands.items():
        q = cmds.add_parser(name, help=desc, description=desc)
        if name not in {"init", "list", "demo"}:
            q.add_argument("--session", help="Review ID, unique prefix or exact title.")
        if name in {"status", "inventory", "review", "analyze"}:
            q.add_argument(
                "--capture",
                dest="capture_id",
                help="Inspect this named historical capture (read-only).",
            )
        if name not in {"export", "web"}:
            q.add_argument(
                "--json", action="store_true", help="Print machine-readable output."
            )
        if name == "init":
            q.add_argument(
                "--config",
                type=Path,
                help="Path to project JSON, including repositories and optional contracts.",
            )
            q.add_argument("--title")
            q.add_argument("--objective")
            q.add_argument(
                "--repo",
                action="append",
                metavar="ALIAS=PATH",
                help="Repeat for related repositories.",
            )
            q.add_argument("--base", default="HEAD")
            q.add_argument("--target", default="WORKTREE")
            q.add_argument("--include-untracked", action="store_true")
            q.add_argument("--criterion", action="append", default=[])
        if name == "capture":
            q.add_argument(
                "--refresh", action="store_true", help="Recapture tracked inputs."
            )
            q.add_argument("--if-version", type=int)
            q.add_argument(
                "--config",
                type=Path,
                help="Approve changed scope using a complete project JSON.",
            )
        if name == "inventory":
            q.add_argument(
                "--all-repos",
                action="store_true",
                help="Include all configured repositories (default).",
            )
            q.add_argument("--repo", help="Restrict output to one repository alias.")
            q.add_argument("--patch", action="store_true")
        if name == "status":
            q.add_argument("--stale", action="store_true")
        if name == "analyze":
            group = q.add_mutually_exclusive_group()
            group.add_argument(
                "--model",
                help="Opt in to review by this locally installed Ollama model.",
            )
            group.add_argument(
                "--packet",
                action="store_true",
                help="Print bounded JSON evidence for an independent reviewer.",
            )
            group.add_argument("--import-report", type=Path)
        if name in ("review", "web"):
            q.add_argument("--unit", help="Review unit ID.")
        if name == "review":
            q.add_argument(
                "--action", choices=["approve", "request_changes", "defer", "dismiss"]
            )
            q.add_argument("--finding", help="Finding ID for a dismissal.")
            q.add_argument("--reason", default="")
            q.add_argument(
                "--if-version",
                type=int,
                help="Reject if a different version is current.",
            )
            q.add_argument(
                "--action-id", help="Unique ID for retrying an identical action."
            )
            q.add_argument(
                "--yes",
                action="store_true",
                help="Confirm the explicitly selected action.",
            )
        if name == "delete":
            q.add_argument(
                "--yes",
                action="store_true",
                help="Confirm removal of the selected review history.",
            )
        if name == "export":
            q.add_argument("--format", choices=["markdown", "json"], default="markdown")
            q.add_argument("--output", type=Path)
        if name == "web":
            q.add_argument(
                "--port",
                type=int,
                default=8765,
                help="Choose a loopback port; 0 selects a free port.",
            )
            q.add_argument("--no-open", action="store_true")
        if name == "check":
            q.add_argument("--repo", required=True)
            q.add_argument("--name", required=True)
            q.add_argument(
                "--yes",
                action="store_true",
                help="Trust the supplied command and repository code to run as your user.",
            )
            q.add_argument(
                "argv", nargs=argparse.REMAINDER, help="Command with arguments after --"
            )
    return p


def _json(obj):
    print(json.dumps(obj, ensure_ascii=True, indent=2))


def _project(path):
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or not isinstance(config.get("repos"), list):
        raise ValueError("Expected a project object with a repos list.")
    for repo in config["repos"]:
        if isinstance(repo, dict) and isinstance(repo.get("path"), str):
            repo["path"] = str(
                (path.resolve().parent / Path(repo["path"]).expanduser()).resolve()
            )
    return config


def _resolve(engine, name):
    sessions = engine.list_sessions()
    if not sessions:
        raise ValueError("There are no saved reviews. Run cor init or cor demo.")
    if name is None and len(sessions) == 1:
        return sessions[0]["id"]
    matches = [
        r["id"]
        for r in sessions
        if name and (r["id"].startswith(name) or r["title"] == name)
    ]
    if len(matches) != 1:
        raise ValueError(
            "Select a unique review with --session. Run cor list to see the available reviews."
        )
    return matches[0]


def summary(v):
    c = v["counts"]
    print(
        f"{v['title']}\nSession  {v['id']}\nCapture  {v['capture']}   ·   version {v['version']}"
    )
    print(
        f"{len(v['repositories'])} repositories  ·  {c['files']} files  ·  {c['units']} decisions  ·  {c['approved']}/{c['atoms']} changes approved"
    )


def show_unit(v, u):
    print(
        f"\n{u['title']}   [{u['risk']} · {u['status']}]\n{u['id']}  |  {', '.join(u['repos'])}\n{u['summary']}"
    )
    if u["reason"]:
        print("Decision note:", u["reason"])
    for r in v["repositories"]:
        for f in r["files"]:
            if f["id"] not in u["file_ids"]:
                continue
            print(f"\n{r['alias']} / {f['path']}   [{f['status']}]")
            for atom in f["atoms"]:
                print(atom["patch"])
    for side, descriptor in u.get("sides", {}).items():
        for ctx in descriptor.get("contexts", []):
            if not descriptor.get("file_ids"):
                print(
                    f"\n{side}: {descriptor['repo']} / {ctx['path']} (frozen context)\n{ctx.get('text') or '[opaque]'}"
                )
    for f in u["findings"]:
        state = (
            "dismissed"
            if f.get("disposition")
            else "blocking"
            if f["blocking"]
            else "advisory"
        )
        print(f"\n[{state}] {f['title']}\n{f['id']}  {f['detail']}")


def _review(engine, v, args):
    if args.capture_id and args.action:
        raise ValueError(
            "Historical captures are read-only. Open the current review to record a decision."
        )
    selected = [u for u in v["units"] if not args.unit or u["id"] == args.unit]
    if args.unit and not selected:
        raise ValueError("Unknown review unit.")
    if args.action:
        if not args.unit or not args.yes:
            raise ValueError(
                "Recording an action requires --unit ID and --yes. Use cor review --unit ID to inspect the changes first."
            )
        payload = dict(
            unit_id=args.unit,
            action=args.action,
            reason=args.reason,
            capture=v["capture"],
            version=args.if_version if args.if_version is not None else v["version"],
            action_id=args.action_id or uuid.uuid4().hex,
        )
        if args.finding:
            payload["finding_id"] = args.finding
        result = engine.decide(v["id"], payload)
        return _json(result) if args.json else summary(result)
    if args.json:
        return _json(selected)
    interactive = sys.stdin.isatty() and not args.capture_id
    if not selected:
        return print("Nothing to review.")
    for u in selected:
        show_unit(v, u)
        if not interactive:
            continue
        key = (
            input(
                "\n[a]pprove  [r]equest changes  [d]efer  [x] dismiss finding  [enter] next  [q]uit > "
            )
            .lower()
            .strip()
        )
        if key == "q":
            break
        action = {
            "a": "approve",
            "r": "request_changes",
            "d": "defer",
            "x": "dismiss",
        }.get(key)
        if not action:
            continue
        payload = dict(
            unit_id=u["id"],
            action=action,
            reason="",
            version=v["version"],
            capture=v["capture"],
            action_id=uuid.uuid4().hex,
        )
        if key == "a":
            if (
                input(f"Approve {len(u['atom_ids'])} changes in {u['title']}? [y/N] ")
                .lower()
                .strip()
                != "y"
            ):
                continue
        else:
            if key == "x":
                payload["finding_id"] = input("Finding ID: ").strip()
            payload["reason"] = input("Reason: ").strip()
        v = engine.decide(v["id"], payload)
        print("Decision saved.")


def execute(args, engine):
    cmd = args.cmd
    if cmd == "list":
        rows = engine.list_sessions()
        if args.json:
            _json(rows)
        else:
            for r in rows:
                print(r["id"], r["title"], sep="  ")
            if not rows:
                print("No reviews yet. Run cor demo or cor init.")
        return
    if cmd == "init":
        if args.config:
            config = _project(args.config)
        else:
            roots = args.repo or []
            title, objective = args.title, args.objective
            if sys.stdin.isatty():
                title = title or input("Review title: ").strip()
                objective = (
                    objective or input("What behavior are you approving? ").strip()
                )
                if not roots:
                    roots = (
                        input(
                            "Git repositories (alias=/path, separate multiple with commas): "
                        )
                        .strip()
                        .split(",")
                    )
            if not title or not objective or not roots:
                raise ValueError(
                    "Supply --config, or --title, --objective and one or more --repo ALIAS=PATH values."
                )
            repos = []
            for spec in roots:
                alias, eq, path = spec.strip().partition("=")
                if not eq or not alias or not path:
                    raise ValueError("Use --repo ALIAS=PATH.")
                repos.append(
                    dict(
                        alias=alias,
                        path=path,
                        base=args.base,
                        target=args.target,
                        include_untracked=args.include_untracked,
                    )
                )
            config = dict(
                title=title,
                objective=objective,
                repos=repos,
                criteria=args.criterion,
                contracts=[],
            )
        v = engine.create(config)
        return _json(v) if args.json else summary(v)
    if cmd == "demo":
        v = demo(engine, engine.home)
        if args.json:
            return _json(v)
        summary(v)
        print("\nEditable example repositories:")
        for repo in v["config"]["repos"]:
            print(repo["path"])
        return
    if cmd == "web":
        from .server import serve

        route = ""
        if args.session or args.unit:
            sid = _resolve(engine, args.session)
            route = (
                "#review/"
                + quote(sid, safe="")
                + (
                    "/decisions/" + quote(args.unit, safe="")
                    if args.unit
                    else "/overview"
                )
            )
        return serve(engine, args.port, not args.no_open, route)
    sid = _resolve(engine, args.session)
    v = engine.get(sid, getattr(args, "capture_id", None))
    if cmd == "delete":
        if not args.session or not args.yes:
            raise ValueError(
                "Supply --session and --yes to remove the selected review."
            )
        engine.delete(sid, v["version"])
        return (
            _json({"deleted": True}) if args.json else print("Review history removed.")
        )
    if cmd == "capture":
        version = args.if_version if args.if_version is not None else v["version"]
        result = (
            engine.update_config(sid, _project(args.config), version)
            if args.config
            else engine.refresh(sid, version)
        )
        return _json(result) if args.json else summary(result)
    if cmd == "status":
        if args.json:
            return _json(
                v
                if not args.stale
                else [u for u in v["units"] if u["status"] == "stale"]
            )
        summary(v)
        for u in v["units"]:
            if not args.stale or u["status"] == "stale":
                print(f"{u['id']}  {u['status']:18} {u['title']}")
    elif cmd == "inventory":
        repos = [
            r for r in v["repositories"] if not args.repo or r["alias"] == args.repo
        ]
        if not repos:
            raise ValueError("Unknown repository.")
        if args.json:
            return _json(repos)
        for r in repos:
            print(f"{r['alias']}  {r['base_sha'][:10]} → {r['target_id'][:10]}")
            for f in r["files"]:
                print(f"  {f['status']}  {f['path']}  ({len(f['atoms'])} changes)")
                if args.patch:
                    for atom in f["atoms"]:
                        print(atom["patch"])
    elif cmd == "review":
        _review(engine, v, args)
    elif cmd == "analyze":
        if args.packet:
            return _json(packet(v))
        if args.capture_id and (args.model or args.import_report):
            raise ValueError("Historical captures are read-only.")
        base = {"version": v["version"], "capture": v["capture"]}
        if args.model:
            v = local_model(engine, sid, dict(base, model=args.model))
        elif args.import_report:
            v = import_report(
                engine,
                sid,
                dict(base, report=json.loads(args.import_report.read_text())),
            )
        if args.json:
            return _json(
                {
                    "analysis": v["analysis"],
                    "passes": v.get("analysis_passes", {}),
                    "units": v["units"],
                }
            )
        for u in v["units"]:
            for f in u["findings"]:
                print(f"{u['title']}  [{f['id']}]\n  {f['title']}\n  {f['detail']}")
        print(
            "Review mode:",
            v["analysis"]["mode"],
            "·",
            len(v.get("analysis_passes", {})),
            "independent passes recorded",
        )
    elif cmd == "history":
        rows = engine.history(sid)
        if args.json:
            return _json(rows)
        for e in rows:
            print(
                f"{e['time']}  {e['action']}  {e.get('unit_id') or ''}  {e['reason']}"
            )
    elif cmd == "check":
        from .checks import run_check

        argv = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
        if not args.yes:
            raise ValueError(
                "Inspect the command, then add --yes to run it with your account's permissions in a disposable copy."
            )
        after = run_check(
            engine,
            sid,
            dict(
                name=args.name,
                repo=args.repo,
                argv=argv,
                version=v["version"],
                capture=v["capture"],
            ),
        )
        check = after["checks"][-1]
        if args.json:
            _json(check)
        else:
            print(check["output"])
            print("Passed" if check["passed"] else "Failed", "·", args.name)
        return 0 if check["passed"] else 1
    elif cmd == "verify":
        result = engine.verify(sid)
        if args.json:
            _json(result)
        else:
            print("Ready for PR review." if result["ready"] else "Review incomplete.")
            for blocker in result["blockers"]:
                print("•", blocker)
        return 0 if result["ready"] else 1
    elif cmd == "export":
        out = engine.export(sid, args.format)
        if args.output:
            args.output.write_text(out, encoding="utf-8")
            print(args.output)
        else:
            print(out, end="" if out.endswith("\n") else "\n")


def main(argv=None):
    args = parser().parse_args(argv)
    if args.home:
        os.environ["COR_HOME"] = str(Path(args.home).expanduser().resolve())
    try:
        return execute(args, Engine()) or 0
    except (ValueError, KeyError, OSError) as e:
        print("cor:", str(e), file=sys.stderr)
        return 2
    except (EOFError, KeyboardInterrupt):
        print("Review closed.", file=sys.stderr)
        return 130
