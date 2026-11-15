"""Read-only signed-release service. Publishing happens offline, never over HTTP."""
import argparse
import hashlib
import json
import re
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit


def create_server(data, host="0.0.0.0", port=8787):
    root = Path(data).resolve()

    class Handler(BaseHTTPRequestHandler):
        server_version = "EchoUpdates/1"

        def do_HEAD(self):
            self.do_GET(head=True)

        def do_GET(self, head=False):
            path = unquote(urlsplit(self.path).path)
            if path in ('/v1/releases/stable/windows-x64','/v2/releases/stable/windows-x64'):
                try:paused=json.loads((root/'control.json').read_text()).get('paused') is True
                except (OSError,ValueError):paused=False
                if paused:
                    self.send_response(503)
                    self.send_header('Retry-After','3600')
                    self.send_header('Content-Length','0')
                    self.end_headers()
                    return
            if path == "/healthz":
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                if not head: self.wfile.write(b"ok")
                return
            if path in ("/v1/releases/stable/windows-x64", "/v1/catalog/stable/windows-x64"):
                file = root / "stable.json"
                content_type = "application/json; charset=utf-8"
            elif path == "/v2/releases/stable/windows-x64":
                file = root / "stable-v2.json"
                content_type = "application/json; charset=utf-8"
            elif re.fullmatch(r"/artifacts/(?:Echo-Setup-\d+\.\d+\.\d+\.exe|Echo-Update-\d+\.\d+\.\d+\.zip)", path):
                file = root / "artifacts" / path.rsplit("/", 1)[-1]
                content_type = "application/octet-stream"
            else:
                self.send_error(404)
                return
            resolved = file.resolve()
            if not resolved.is_relative_to(root) or not resolved.is_file():
                self.send_error(404, "Release not published")
                return
            try:
                with resolved.open("rb") as stream:
                    size = os.fstat(stream.fileno()).st_size
                    self.send_response(200)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(size))
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.send_header("Cache-Control", "no-store" if path.endswith("windows-x64") else "public, max-age=3600")
                    self.end_headers()
                    if not head:
                        while chunk := stream.read(128 * 1024):
                            self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def log_message(self, format, *args):
            # No query strings, client identifiers or user learning data in logs.
            pass

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=os.getenv("ECHO_RELEASE_DATA", "/data"))
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    create_server(args.data, port=args.port).serve_forever()
