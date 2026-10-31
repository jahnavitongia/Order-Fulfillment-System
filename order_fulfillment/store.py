"""SQLite persistence: inventory, orders, shipments and workflow checkpoints.

A new connection is opened per call, which keeps this safe to use from the
threaded HTTP server and from tests.  Default database file: ./order_fulfillment.db
(override with the ORDER_DB environment variable).
"""
import json
import os
import sqlite3
import tempfile
import time
from contextlib import closing

from .config import SEED_ITEMS

SCHEMA = """
CREATE TABLE IF NOT EXISTS inventory (
    item TEXT PRIMARY KEY,
    stock INTEGER NOT NULL,
    unit_price REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    thread_id TEXT PRIMARY KEY,
    item TEXT, qty INTEGER, unit_price REAL, order_value REAL,
    status TEXT, reason TEXT, courier TEXT, shipping_cost REAL,
    approval TEXT, approver TEXT,
    created_at REAL, updated_at REAL
);
CREATE TABLE IF NOT EXISTS shipments (
    thread_id TEXT PRIMARY KEY,
    courier TEXT, cost REAL, eta_days INTEGER, tracking_ref TEXT, booked_at REAL
);
CREATE TABLE IF NOT EXISTS checkpoints (
    thread_id TEXT NOT NULL,
    step INTEGER NOT NULL,
    node TEXT NOT NULL,
    state_json TEXT NOT NULL,
    created_at REAL,
    PRIMARY KEY (thread_id, step)
);
CREATE TABLE IF NOT EXISTS customer_memory (
    customer TEXT NOT NULL,
    key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    updated_at REAL,
    PRIMARY KEY (customer, key)
);
"""


class Store:
    def __init__(self, path: str):
        self.path = path
        with closing(self._conn()) as c:
            c.executescript(SCHEMA)
            if c.execute("SELECT COUNT(*) FROM inventory").fetchone()[0] == 0:
                c.executemany("INSERT INTO inventory VALUES (?,?,?)",
                              [(k, s, p) for k, (s, p) in SEED_ITEMS.items()])
            c.commit()

    @classmethod
    def fresh(cls) -> "Store":
        """A brand-new, freshly seeded database in a temp folder (used by demos/tests)."""
        return cls(os.path.join(tempfile.mkdtemp(prefix="orders_"), "orders.db"))

    def _conn(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    # ---------------- inventory ----------------
    def get_item(self, item: str):
        with closing(self._conn()) as c:
            r = c.execute("SELECT * FROM inventory WHERE item=?", (item,)).fetchone()
            return dict(r) if r else None

    def list_inventory(self):
        with closing(self._conn()) as c:
            return [dict(r) for r in c.execute("SELECT * FROM inventory ORDER BY item")]

    def reserve_stock(self, item: str, qty: int) -> bool:
        """ATOMIC guarded decrement: succeeds only if stock >= qty at this very moment."""
        with closing(self._conn()) as c:
            cur = c.execute("UPDATE inventory SET stock = stock - ? WHERE item=? AND stock >= ?",
                            (qty, item, qty))
            c.commit()
            return cur.rowcount == 1

    def force_decrement(self, item: str, qty: int) -> bool:
        """UNSAFE decrement (no guard) - exists only to demonstrate error propagation."""
        with closing(self._conn()) as c:
            cur = c.execute("UPDATE inventory SET stock = stock - ? WHERE item=?", (qty, item))
            c.commit()
            return cur.rowcount == 1

    def reset_inventory(self):
        with closing(self._conn()) as c:
            c.executemany("UPDATE inventory SET stock=? WHERE item=?",
                          [(s, k) for k, (s, _) in SEED_ITEMS.items()])
            c.commit()

    # ---------------- orders / shipments ----------------
    def upsert_order(self, thread_id: str, **fields):
        now = time.time()
        with closing(self._conn()) as c:
            if c.execute("SELECT 1 FROM orders WHERE thread_id=?", (thread_id,)).fetchone():
                if fields:
                    sets = ", ".join(f"{k}=?" for k in fields) + ", updated_at=?"
                    c.execute(f"UPDATE orders SET {sets} WHERE thread_id=?",
                              (*fields.values(), now, thread_id))
            else:
                cols = ["thread_id", *fields.keys(), "created_at", "updated_at"]
                c.execute(f"INSERT INTO orders ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                          (thread_id, *fields.values(), now, now))
            c.commit()

    def get_order(self, thread_id: str):
        with closing(self._conn()) as c:
            r = c.execute("SELECT * FROM orders WHERE thread_id=?", (thread_id,)).fetchone()
            return dict(r) if r else None

    def list_orders(self):
        with closing(self._conn()) as c:
            return [dict(r) for r in c.execute("SELECT * FROM orders ORDER BY created_at")]

    def book_shipment(self, thread_id, courier, cost, eta_days) -> str:
        ref = f"TRK-{thread_id[:6].upper()}"
        with closing(self._conn()) as c:
            c.execute("INSERT OR REPLACE INTO shipments VALUES (?,?,?,?,?,?)",
                      (thread_id, courier, cost, eta_days, ref, time.time()))
            c.commit()
        return ref

    def list_shipments(self):
        with closing(self._conn()) as c:
            return [dict(r) for r in c.execute("SELECT * FROM shipments")]

    # ---------------- checkpoints ----------------
    def save_checkpoint(self, thread_id: str, step: int, node: str, state: dict):
        with closing(self._conn()) as c:
            c.execute("INSERT OR REPLACE INTO checkpoints VALUES (?,?,?,?,?)",
                      (thread_id, step, node, json.dumps(state, default=str), time.time()))
            c.commit()

    def latest_checkpoint(self, thread_id: str):
        with closing(self._conn()) as c:
            r = c.execute("SELECT * FROM checkpoints WHERE thread_id=? ORDER BY step DESC LIMIT 1",
                          (thread_id,)).fetchone()
            if not r:
                return None
            return {"step": r["step"], "node": r["node"], "state": json.loads(r["state_json"])}

    def list_checkpoints(self, thread_id: str):
        with closing(self._conn()) as c:
            return [dict(r) for r in c.execute(
                "SELECT thread_id, step, node FROM checkpoints WHERE thread_id=? ORDER BY step",
                (thread_id,))]


    # ---------------- long-term memory (per customer, survives restarts) ----------------
    def remember(self, customer: str, key: str, value):
        with closing(self._conn()) as c:
            c.execute("INSERT OR REPLACE INTO customer_memory VALUES (?,?,?,?)",
                      (customer, key, json.dumps(value), time.time()))
            c.commit()

    def recall(self, customer: str) -> dict:
        with closing(self._conn()) as c:
            return {r["key"]: json.loads(r["value_json"]) for r in c.execute(
                "SELECT key, value_json FROM customer_memory WHERE customer=?", (customer,))}


_STORE = None


def get_store() -> Store:
    global _STORE
    if _STORE is None:
        default = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "order_fulfillment.db")
        _STORE = Store(os.environ.get("ORDER_DB", default))
    return _STORE


def use_store(store: Store) -> Store:
    """Swap the active store (tests and demos use fresh temp databases)."""
    global _STORE
    _STORE = store
    return store
