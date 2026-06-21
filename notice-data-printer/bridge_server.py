#!/usr/bin/env python3
"""Tiny localhost queue bridge between the Python notice GUI and Chrome extension.

The Python GUI runs this server on 127.0.0.1. The extension polls it and
loads queued generated payloads, then applies its URL form-fill profiles.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional

_LOCK = threading.RLock()
_QUEUE: List[Dict[str, Any]] = []
_SERVER: Optional[ThreadingHTTPServer] = None
_THREAD: Optional[threading.Thread] = None
_PORT: Optional[int] = None


def _json_bytes(obj: Any, status: int = 200) -> bytes:
    return json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")


def payload_signature(payload: Dict[str, Any]) -> str:
    rendered = payload.get("rendered", {}) if isinstance(payload, dict) else {}
    case_data = payload.get("case_data", {}) if isinstance(payload, dict) else {}
    fill_values = (payload.get("extension_payload", {}) or {}).get("fill_values", {}) if isinstance(payload, dict) else {}
    seed = {
        "domain": case_data.get("domain") or fill_values.get("domain"),
        "template_id": case_data.get("template_id") or fill_values.get("template_id"),
        "notice_text": rendered.get("notice_text") or fill_values.get("notice_text"),
        "subject": rendered.get("subject") or fill_values.get("subject"),
    }
    raw = json.dumps(seed, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def make_queue_item(payload: Dict[str, Any], title: str = "", source: str = "python-gui") -> Dict[str, Any]:
    now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    case_data = payload.get("case_data", {}) if isinstance(payload, dict) else {}
    rendered = payload.get("rendered", {}) if isinstance(payload, dict) else {}
    fill_values = (payload.get("extension_payload", {}) or {}).get("fill_values", {}) if isinstance(payload, dict) else {}
    domain = case_data.get("domain") or fill_values.get("domain") or "unknown-domain"
    template_id = case_data.get("template_id") or fill_values.get("template_id") or "unknown-template"
    subject = rendered.get("subject") or fill_values.get("subject") or ""
    if not title:
        title = subject or f"{domain} - {template_id}"
    return {
        "id": uuid.uuid4().hex,
        "signature": payload_signature(payload),
        "title": title,
        "domain": domain,
        "template_id": template_id,
        "source": source,
        "created_at": now,
        "updated_at": now,
        "payload": payload,
    }


def enqueue(payload: Dict[str, Any], title: str = "", source: str = "python-gui") -> Dict[str, Any]:
    """Add or update a queue item. Same signature updates existing item."""
    item = make_queue_item(payload, title=title, source=source)
    with _LOCK:
        for existing in _QUEUE:
            if existing.get("signature") == item["signature"]:
                existing.update({
                    "title": item["title"],
                    "domain": item["domain"],
                    "template_id": item["template_id"],
                    "source": item["source"],
                    "updated_at": item["updated_at"],
                    "payload": item["payload"],
                })
                return existing
        _QUEUE.insert(0, item)
        # Keep the queue small enough for the popup UI.
        del _QUEUE[50:]
        return item


def list_items() -> List[Dict[str, Any]]:
    with _LOCK:
        return json.loads(json.dumps(_QUEUE, ensure_ascii=False))


def delete_item(item_id: str) -> int:
    with _LOCK:
        before = len(_QUEUE)
        _QUEUE[:] = [item for item in _QUEUE if item.get("id") != item_id]
        return before - len(_QUEUE)


def clear_queue() -> int:
    with _LOCK:
        count = len(_QUEUE)
        _QUEUE.clear()
        return count


class BridgeHandler(BaseHTTPRequestHandler):
    server_version = "NoticeBridge/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        # Keep GUI terminal quiet.
        return

    def _send_json(self, obj: Any, status: int = 200) -> None:
        data = _json_bytes(obj)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw.strip() else {}

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send_json({"ok": True})

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/health"):
            self._send_json({"ok": True, "count": len(list_items()), "port": _PORT})
            return
        if self.path.startswith("/queue"):
            self._send_json({"ok": True, "items": list_items(), "count": len(list_items())})
            return
        self._send_json({"ok": False, "error": "Not found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        try:
            body = self._read_json()
            if self.path.startswith("/enqueue"):
                payload = body.get("payload") if isinstance(body, dict) and "payload" in body else body
                title = body.get("title", "") if isinstance(body, dict) else ""
                if not isinstance(payload, dict):
                    self._send_json({"ok": False, "error": "Payload must be a JSON object"}, status=400)
                    return
                item = enqueue(payload, title=title, source="http")
                self._send_json({"ok": True, "item": item, "count": len(list_items())})
                return
            if self.path.startswith("/delete"):
                item_id = str(body.get("id", ""))
                self._send_json({"ok": True, "deleted": delete_item(item_id), "count": len(list_items())})
                return
            if self.path.startswith("/clear"):
                self._send_json({"ok": True, "cleared": clear_queue(), "count": 0})
                return
            self._send_json({"ok": False, "error": "Not found"}, status=404)
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=500)


def start_server(host: str = "127.0.0.1", port: int = 8765) -> int:
    global _SERVER, _THREAD, _PORT
    if _SERVER is not None:
        return int(_PORT or port)
    httpd = ThreadingHTTPServer((host, port), BridgeHandler)
    _SERVER = httpd
    _PORT = int(httpd.server_address[1])
    _THREAD = threading.Thread(target=httpd.serve_forever, name="notice-bridge-server", daemon=True)
    _THREAD.start()
    return _PORT


def stop_server() -> None:
    global _SERVER, _THREAD, _PORT
    if _SERVER is not None:
        _SERVER.shutdown()
        _SERVER.server_close()
    _SERVER = None
    _THREAD = None
    _PORT = None


def is_running() -> bool:
    return _SERVER is not None


if __name__ == "__main__":
    port = start_server()
    print(f"Notice bridge running at http://127.0.0.1:{port}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop_server()
