"""HTTP API for the dashboard, backed by the TA2 graph (stdlib only). Ollama must be running.

    python ta2/server.py            # http://localhost:8000

    GET  /health                    model names
    GET  /state                     stock, approval queue, recent orders
    GET  /customer?name=            long-term memory for one customer (SqliteStore)
    POST /order    {customer, thread_id?, item?, qty?, weight?, distance?, request?, stale_cache?, quote_failures?}
    POST /approve  {thread_id, decision: approved|rejected}
    POST /resume   {thread_id}      continue a failed order from its checkpoint
    POST /ask      {question}       policy answer (RAG) + the cited clauses
    POST /reset    {}               full stock, empty queue and order list (customer memory is kept)
"""
import json, os, re, threading, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from demo import fresh, ask, approve, resume, cfg
from order_ta2 import STOCK, CACHE, SEED, COURIERS, THRESHOLD, policy_db

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 8000
APP = fresh(os.path.join(HERE, "ui"))      # ui_threads.db + ui_store.db: memory survives a server restart
LOCK = threading.Lock()                    # ponytail: one graph run at a time; fine for a single-desk demo
ORDERS, PENDING = [], {}                   # recent results + approval queue (RAM, cleared on restart)


def bid_rows(r):
    """Every courier, with its bid or the reason it refused (only when shipping ran this turn)."""
    if not any(line.startswith("[shipping_agent]") for line in r.get("trace", [])):
        return []
    w, d, bids = r["weight"], r["distance"], (r.get("bids") or {}) if r.get("courier") else {}
    rows = []
    for name, (_, _, _, max_kg, max_km, eta) in COURIERS.items():
        reason = (f"max {max_kg} kg" if w > max_kg else f"max {max_km} km" if d > max_km else "")
        rows.append({"courier": name, "price": bids.get(name), "eta": eta, "refused": reason,
                     "winner": name == r.get("courier")})
    return sorted(rows, key=lambda b: (b["price"] is None, b["price"] or 0))


def view(r, thread, customer):
    paused = "__interrupt__" in r
    qty, item = r.get("qty"), r.get("item")
    unit = SEED.get(item, (0, 0))[1]
    out = {"thread_id": thread, "customer": customer, "status": "awaiting_approval" if paused else r.get("status"),
           "message": r.get("message", ""), "item": item, "qty": qty, "weight": r.get("weight"),
           "distance": r.get("distance"), "courier": r.get("courier") or None, "price": r.get("price"),
           "eta": r.get("eta"), "goods_value": round(qty * unit, 2) if isinstance(qty, int) else None,
           "claimed": r.get("claimed"), "bids": bid_rows(r), "trace": r.get("trace", [])}
    if paused:
        PENDING[thread] = out
    else:
        PENDING.pop(thread, None)
        if out["status"] in ("confirmed", "declined", "failed"):
            ORDERS.insert(0, {k: out[k] for k in ("thread_id", "customer", "status", "item", "qty", "goods_value",
                                                  "courier", "price")})
            del ORDERS[25:]
    return out


def place(p):
    customer = (p.get("customer") or "guest").strip() or "guest"
    thread = p.get("thread_id") or uuid.uuid4().hex[:8]
    fields = {k: p[k] for k in ("item", "weight", "distance") if p.get(k) not in (None, "")}
    if p.get("qty") not in (None, ""):
        fields["qty"] = int(float(p["qty"]))
    for k in ("weight", "distance"):
        if k in fields:
            fields[k] = float(fields[k])
    item = fields.get("item") or APP.get_state(cfg(thread)).values.get("item")
    if p.get("stale_cache") and item in STOCK:
        CACHE[item] = STOCK[item] + 100                                   # demo: inventory agent reads a wrong cache
    try:
        r = ask(APP, thread, customer, request=p.get("request", "order"),
                fail_quotes=int(p.get("quote_failures") or 0), **fields)
    finally:
        CACHE.update(STOCK)
    return view(r, thread, customer)


def answer(question):
    r = ask(APP, "q-" + uuid.uuid4().hex[:8], request="question", question=question)
    ids = list(dict.fromkeys(re.findall(r"\[(\d+\.\d+)\]", r["message"])))
    docs = policy_db().get(ids=ids)["documents"] if ids else []
    return {"answer": r["message"], "known": bool(ids),
            "citations": [{"id": i, "text": t} for i, t in zip(ids, docs)]}


def state():
    return {"threshold": THRESHOLD, "pending": list(PENDING.values()), "orders": ORDERS,
            "inventory": [{"item": k, "stock": STOCK[k], "start": SEED[k][0], "price": SEED[k][1]} for k in SEED]}


def reset():
    STOCK.update({k: v[0] for k, v in SEED.items()}); CACHE.update(STOCK)
    ORDERS.clear(); PENDING.clear()
    return state()


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        for h, v in (("Content-Type", "application/json"), ("Content-Length", str(len(data))),
                     ("Access-Control-Allow-Origin", "*"), ("Access-Control-Allow-Headers", "Content-Type"),
                     ("Access-Control-Allow-Methods", "GET, POST, OPTIONS")):
            self.send_header(h, v)
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self._send(204, {})

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/health":
            return self._send(200, {"ok": True, "model": "qwen2.5:3b", "embed": "nomic-embed-text"})
        if url.path == "/state":
            return self._send(200, state())
        if url.path == "/customer":
            name = parse_qs(url.query).get("name", [""])[0].strip()
            prof = APP.store.get(("customers", name), "profile") if name else None
            return self._send(200, {"customer": name, "last_order": prof.value if prof else None})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        try:
            p = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            with LOCK:
                if self.path == "/order":
                    return self._send(200, place(p))
                if self.path == "/approve":
                    if p["thread_id"] not in PENDING:
                        return self._send(409, {"error": "That order is no longer waiting for approval."})
                    customer = PENDING[p["thread_id"]]["customer"]
                    return self._send(200, view(approve(APP, p["thread_id"], p["decision"]), p["thread_id"], customer))
                if self.path == "/resume":
                    r = resume(APP, p["thread_id"])
                    return self._send(200, view(r, p["thread_id"], r.get("customer", "guest")))
                if self.path == "/ask":
                    q = (p.get("question") or "").strip()
                    return self._send(200, answer(q)) if q else self._send(400, {"error": "Type a question first."})
                if self.path == "/reset":
                    return self._send(200, reset())
            self._send(404, {"error": "not found"})
        except (KeyError, ValueError, json.JSONDecodeError) as e:
            self._send(400, {"error": f"Bad request: {e}"})
        except Exception as e:                                            # e.g. Ollama not running
            self._send(500, {"error": f"{type(e).__name__}: {e}"})

    def log_message(self, fmt, *args):
        print("[server]", fmt % args)


if __name__ == "__main__":
    print(f"TA2 dashboard API on http://localhost:{PORT}  (Ollama: qwen2.5:3b + nomic-embed-text)")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
