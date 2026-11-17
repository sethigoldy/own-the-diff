"""Local browser transport. Domain operations live in the same engine used by the CLI."""

import hmac
import json
import mimetypes
import os
import secrets
import subprocess
import sys
import threading
import traceback
import webbrowser
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, unquote

from . import assistance
from .demo import demo
from .engine import Conflict

STATIC = Path(__file__).parent / "static"


def pick_folder():
    if sys.platform != "darwin":
        raise ValueError("Enter the absolute path to your local Git checkout.")
    try:
        proc = subprocess.run(
            [
                "/usr/bin/osascript",
                "-e",
                'POSIX path of (choose folder with prompt "Select a local Git repository")',
            ],
            capture_output=True,
            text=True,
            timeout=100,
        )
    except subprocess.TimeoutExpired:
        raise ValueError("Folder selection timed out. Try again or enter its path.")
    if proc.returncode and "-128" not in proc.stderr:
        raise ValueError(
            "The system folder picker is unavailable. Enter a local path instead."
        )
    return {"path": proc.stdout.strip() or None}


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port, engine):
        self.engine = engine
        self.secret = secrets.token_urlsafe(32)
        super().__init__(("127.0.0.1", port), BrowserRequest)


class BrowserRequest(BaseHTTPRequestHandler):
    server_version = "CodeOwnershipReview"

    def log_message(self, fmt, *args):
        if os.environ.get("COR_HTTP_LOG"):
            super().log_message(fmt, *args)

    def send_data(
        self,
        status,
        body,
        kind="application/json; charset=utf-8",
        cookie=False,
        attachment=None,
    ):
        if not isinstance(body, bytes):
            body = (
                json.dumps(body, ensure_ascii=True)
                if kind.startswith("application/json")
                else body
            ).encode()
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; font-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'; object-src 'none'",
        )
        if cookie:
            self.send_header(
                "Set-Cookie",
                f"cor_session_{self.server.server_port}={self.server.secret}; HttpOnly; SameSite=Strict; Path=/",
            )
        if attachment:
            self.send_header(
                "Content-Disposition", f'attachment; filename="{attachment}"'
            )
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.dispatch(False)

    def do_POST(self):
        self.dispatch(True)

    def dispatch(self, mutation):
        try:
            port = self.server.server_port
            host = self.headers.get("Host", "")
            if host not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
                return self.send_data(
                    403, {"error": "Use the local workspace address."}
                )
            if self.headers.get("Origin") not in (None, "http://" + host):
                return self.send_data(
                    403, {"error": "Request origin does not match this workspace."}
                )
            url = urlsplit(self.path)
            path = unquote(url.path)
            if not path.startswith("/api/") and not mutation:
                return self.static(path)
            if self.headers.get("Sec-Fetch-Site") == "cross-site":
                return self.send_data(403, {"error": "Open this workspace directly."})
            cookies = SimpleCookie()
            cookies.load(self.headers.get("Cookie", ""))
            token = cookies.get(f"cor_session_{port}")
            if not token or not hmac.compare_digest(token.value, self.server.secret):
                return self.send_data(
                    403,
                    {
                        "error": "Reload the local application to start a browser session."
                    },
                )
            if mutation:
                if (
                    self.headers.get_content_type() != "application/json"
                    or self.headers.get("X-COR-Request") != "1"
                ):
                    return self.send_data(
                        403,
                        {
                            "error": "Expected a JSON request from the local application."
                        },
                    )
                n = int(self.headers.get("Content-Length", -1))
                if not 0 <= n <= 4_194_304:
                    return self.send_data(
                        413, {"error": "Request body exceeds 4 MiB or is missing."}
                    )
                data = json.loads(self.rfile.read(n))
                if not isinstance(data, dict):
                    raise ValueError("The request must be a JSON object.")
            else:
                data = {}
            segments = path.strip("/").split("/")
            query = {k: vs[0] for k, vs in parse_qs(url.query).items()}
            return self.api(segments, query, data, mutation)
        except Conflict as exc:
            self.send_data(409, {"error": str(exc)})
        except KeyError as exc:
            self.send_data(404, {"error": f"Unknown review resource: {exc}"})
        except (ValueError, CookieError, TypeError, UnicodeError) as exc:
            self.send_data(400, {"error": str(exc)})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            traceback.print_exc()
            self.send_data(
                500,
                {
                    "error": "The local service could not finish the operation. See the server log."
                },
            )

    def static(self, path):
        candidate = (STATIC / (path.lstrip("/") or "index.html")).resolve()
        if not candidate.is_relative_to(STATIC.resolve()) or not candidate.is_file():
            return self.send_data(404, {"error": "Resource not found."})
        body = candidate.read_bytes()
        kind = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
        self.send_data(200, body, kind=kind, cookie=candidate == STATIC / "index.html")

    def api(self, segments, query, data, mutation):
        engine = self.server.engine
        if segments == ["api", "demo"] and mutation:
            result = demo(engine, engine.home)
        elif segments == ["api", "folder"] and mutation:
            result = pick_folder()
        elif segments == ["api", "sessions"]:
            result = (
                engine.create(data)
                if mutation
                else {"sessions": engine.list_sessions()}
            )
        elif len(segments) in (3, 4) and segments[:2] == ["api", "sessions"]:
            sid = segments[2]
            op = segments[3] if len(segments) == 4 else ""
            if mutation:
                if op == "refresh":
                    result = engine.refresh(sid, data.get("version"))
                elif op == "config":
                    result = engine.update_config(
                        sid, data.get("config"), data.get("version")
                    )
                elif op == "delete":
                    engine.delete(sid, data.get("version"))
                    result = {"deleted": True}
                elif op == "decisions":
                    result = engine.decide(sid, data)
                elif op == "analyze":
                    result = assistance.local_model(engine, sid, data)
                elif op == "import":
                    result = assistance.import_report(engine, sid, data)
                elif op == "check":
                    from .checks import run_check

                    result = run_check(engine, sid, data)
                else:
                    return self.send_data(404, {"error": "Unknown operation."})
            elif op == "":
                result = engine.get(sid, query.get("capture"))
            elif op == "revision":
                result = engine.revision(sid)
            elif op == "history":
                result = {"events": engine.history(sid)}
            elif op == "verify":
                result = engine.verify(sid)
            elif op == "packet":
                return self.send_data(
                    200,
                    assistance.packet(engine.get(sid)),
                    attachment="review-packet.json",
                )
            elif op == "export":
                fmt = query.get("format", "markdown")
                if fmt not in ("json", "markdown"):
                    raise ValueError("Format must be json or markdown.")
                result = engine.export(sid, fmt)
                body = (
                    result.encode()
                    if isinstance(result, str)
                    else json.dumps(result).encode()
                )
                return self.send_data(
                    200,
                    body,
                    kind="application/json"
                    if fmt == "json"
                    else "text/markdown; charset=utf-8",
                    attachment="review-ledger.json"
                    if fmt == "json"
                    else "review-summary.md",
                )
            else:
                return self.send_data(404, {"error": "Unknown operation."})
        else:
            return self.send_data(404, {"error": "Unknown resource."})
        self.send_data(200, result)


def serve(engine, port=8765, open_browser=True, route=""):
    if not (STATIC / "index.html").is_file():
        raise ValueError(
            "Browser assets are missing. From the source directory, run npm --prefix web ci and npm --prefix web run build."
        )
    from .launch import running_port, save_server

    existing = running_port(engine)
    if existing is not None and port in (0, 8765, existing):
        url = f"http://127.0.0.1:{existing}/{route}"
        print(url, flush=True)
        if open_browser:
            webbrowser.open(url)
        return
    server = LocalServer(port, engine)
    save_server(engine, server)
    url = f"http://127.0.0.1:{server.server_port}/{route}"
    print(url, flush=True)
    if open_browser:
        threading.Timer(0.25, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
