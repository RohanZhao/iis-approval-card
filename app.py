"""Approval-card prototype: local server.

Run:   python3 app.py
Open:  http://127.0.0.1:8000

Python standard library only; nothing to install.
Everything is a simulation: the shop is made-up data (data/listings.json),
the "model" is mock_model.py, and no real order or payment can happen.
"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import mock_shop
import validator
from agent import Task

ROOT = Path(__file__).parent
STATIC = ROOT / "static"
TASKS = {}

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/listings":
            listings = mock_shop.load_listings()
            for l in listings:   # same rounding as the card, so the two never disagree
                l["unit_labels"] = {k: validator.unit_label(v, l["pack_size"]) for k, v in l["prices"].items()}
            return self._send_json({"listings": listings, "scenarios": mock_shop.SCENARIOS})
        return self._send_static(self.path)

    def do_POST(self):
        body = self._read_json()
        parts = self.path.strip("/").split("/")   # api/task[/<id>/<action>]
        try:
            if parts == ["api", "task"]:
                text = str(body.get("text", "")).strip()
                if not text:
                    return self._send_json({"error": "Please type a request."}, status=400)
                task = Task(text, body.get("scenario", "normal"), body.get("variant", "disclosure"))
                TASKS[task.id] = task
                return self._send_json(task.view())
            if len(parts) == 4 and parts[:2] == ["api", "task"]:
                task = TASKS.get(parts[2])
                if task is None:
                    return self._send_json({"error": "Unknown task."}, status=404)
                result = self._act(task, parts[3], body)
                view = task.view()
                if result:
                    view["result"] = result
                return self._send_json(view)
        except ValueError as e:
            return self._send_json({"error": str(e)}, status=400)
        return self._send_json({"error": "Not found"}, status=404)

    @staticmethod
    def _act(task, action, body):
        if action == "close":
            return task.close_clarification()
        if action == "resume":
            return task.resume()
        if action == "confirm":
            return task.confirm(body.get("answers", {}))
        if action == "retry":
            return task.retry()
        if action == "change":
            return task.change(body["field"], body["value"])
        if action == "acknowledge":
            return task.acknowledge_terms(body.get("value", True))
        if action == "buy":
            return task.buy(body.get("snapshot"))
        if action == "cancel":
            return task.cancel()
        if action == "variant":
            return task.set_variant(body.get("variant"))
        raise ValueError(f"Unknown action: {action}")

    # --- helpers ---------------------------------------------------------

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            return {}

    def _send_json(self, data, status=200):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_static(self, path):
        name = "index.html" if path in ("/", "") else path.split("?")[0].lstrip("/")
        file = (STATIC / name).resolve()
        # Only serve files that are really inside static/.
        if STATIC.resolve() not in file.parents or not file.is_file():
            return self._send_json({"error": "Not found"}, status=404)
        payload = file.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(file.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        pass  # keep the terminal quiet


if __name__ == "__main__":
    address = ("127.0.0.1", 8000)
    print("Approval-card prototype running at http://127.0.0.1:8000  (Ctrl+C to stop)")
    ThreadingHTTPServer(address, Handler).serve_forever()
