"""Start the workspace from Finder, or reopen its already-running local server."""

import json
import os
from http.client import HTTPConnection

from .engine import Engine
from .server import serve


def running_port(engine):
    record = engine.home / "web-launch.json"
    try:
        saved = json.loads(record.read_text())
        port = int(saved["port"])
        conn = HTTPConnection("127.0.0.1", port, timeout=1)
        try:
            conn.request("GET", "/", headers={"Host": f"127.0.0.1:{port}"})
            response = conn.getresponse()
            if response.status == 200 and response.getheader(
                "Set-Cookie", ""
            ).startswith(f"cor_session_{port}=" + saved["token"] + ";"):
                response.read()
                return port
        finally:
            conn.close()
    except (ValueError, OSError, KeyError):
        pass
    return None


def save_server(engine, server):
    record = engine.home / "web-launch.json"
    temp = record.with_name(f".web-launch-{os.getpid()}")
    with temp.open("w") as f:
        os.chmod(temp, 0o600)
        json.dump({"port": server.server_port, "token": server.secret}, f)
    temp.replace(record)


def launch():
    serve(Engine(), port=0)


if __name__ == "__main__":
    launch()
