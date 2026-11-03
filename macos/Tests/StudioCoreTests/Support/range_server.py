"""A small HTTP server for StudioCore's download tests: serves a made-up file of N bytes at /file, with HTTP range
requests (206) – or without them at /norange (always 200, the whole file).

    python3 range_server.py N      (prints the port on its first line, then serves until stdin closes)
"""

import http.server
import sys
import threading

SIZE = int(sys.argv[1]) if len(sys.argv) > 1 else 1_000_000
DATA = bytes((i * 7 + i // 251) % 256 for i in range(SIZE))


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path not in ("/file", "/norange"):
            self.send_error(404)
            return
        start = 0
        rng = self.headers.get("Range", "")
        if self.path == "/file" and rng.startswith("bytes="):
            start = int(rng[6:].split("-")[0] or 0)
            if start >= SIZE:
                self.send_response(416)
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{SIZE - 1}/{SIZE}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(SIZE - start))
        self.end_headers()
        self.wfile.write(DATA[start:])


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
print(server.server_address[1], flush=True)
threading.Thread(target=server.serve_forever, daemon=True).start()
sys.stdin.read()  # until the test closes it
