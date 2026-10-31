"""Dependency-free HTTP backend for the React UI.

    python server.py            # listens on http://localhost:8000

    POST /place_order   {item, requested_qty, weight_kg, distance_km}
    POST /approve       {thread_id, decision: "approved"|"rejected", approver?}
    POST /resume        {thread_id}                  (resume an interrupted order)
    POST /reset         {}                           (re-seed inventory, clear orders for a clean demo)
    POST /chat          {conversation_id, customer?, message}   supervisor + 4 agents + memory
    GET  /orders        orders + shipments + inventory
    GET  /policy?q=...  RAG answer from shipping_policy.md
    GET  /health
Data lives in ./order_fulfillment.db (SQLite) and survives restarts.
"""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from order_fulfillment.runner import process_order, approve_order, resume_order, to_response, engine_name
from order_fulfillment.llm import model_name
from order_fulfillment.store import get_store
from order_fulfillment.rag import ask_policy
from order_fulfillment.supervisor import Supervisor

PORT = 8000
_CHATS = {}   # conversation_id -> Supervisor (its short-term memory lives in RAM)


def _reset():
    store = get_store()
    from contextlib import closing
    with closing(store._conn()) as c:
        for t in ("orders", "shipments", "checkpoints"):
            c.execute(f"DELETE FROM {t}")
        c.commit()
    store.reset_inventory()
    return {"ok": True, "inventory": store.list_inventory()}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self._send(204, {})

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/health":
            self._send(200, {"ok": True, "engine": engine_name(), "model": model_name()})
        elif url.path == "/orders":
            s = get_store()
            self._send(200, {"orders": s.list_orders(), "shipments": s.list_shipments(),
                             "inventory": s.list_inventory()})
        elif url.path == "/policy":
            q = parse_qs(url.query).get("q", [""])[0]
            self._send(200, ask_policy(q)) if q else self._send(400, {"error": "missing ?q="})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
            if self.path == "/place_order":
                self._send(200, process_order(payload))
            elif self.path == "/approve":
                self._send(200, approve_order(payload["thread_id"], payload["decision"],
                                              payload.get("approver", "UI approver")))
            elif self.path == "/resume":
                self._send(200, to_response(resume_order(payload["thread_id"])))
            elif self.path == "/chat":
                sup = _CHATS.setdefault(payload["conversation_id"],
                                        Supervisor(payload.get("customer", "guest")))
                self._send(200, sup.handle(payload["message"]))
            elif self.path == "/reset":
                self._send(200, _reset())
            else:
                self._send(404, {"error": "not found"})
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            self._send(400, {"error": str(e)})
        except Exception as e:  # never crash the demo
            self._send(500, {"error": f"internal error: {e}"})

    def log_message(self, fmt, *args):
        print("[server]", fmt % args)


if __name__ == "__main__":
    print(f"Engine: {engine_name()} | model: {model_name()}")
    print(f"Database: {get_store().path}")
    print(f"Serving on http://localhost:{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
