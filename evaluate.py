"""Evaluation: the SAME 5 test cases on TA1 and TA2, compared with numbers.  Run:

    python evaluate.py > evaluation_results.txt

TA1 = Jury-1 baseline: one fixed LangGraph pipeline, one complete order per message. No memory,
      no policy agent, no supervisor; trusts the Inventory agent's answer and deducts stock
      without a guard (the Jury-1 limitations).
TA2 = Jury-2 system: Supervisor routing to 4 agents (inventory, shipping, order, policy),
      short + long-term memory, inventory verification and the guarded atomic commit.

Both get the same text messages and the same message parser, so the only difference is the
architecture. Every case runs on a fresh seeded SQLite database. LLM is off by default so the
numbers are repeatable (set ORDER_USE_LLM=1 to include Ollama).
"""
import os
import time

os.environ.setdefault("ORDER_USE_LLM", "0")

from order_fulfillment import runner  # noqa: E402
from order_fulfillment.runner import run_order, to_response  # noqa: E402
from order_fulfillment.store import Store, use_store  # noqa: E402
from order_fulfillment.supervisor import Supervisor, find_item, _num, _QTY, _KG, _KM  # noqa: E402


class TA1:
    name = "TA1"

    def __init__(self, **flags):
        self.flags, self.last_order, self.hops = flags, None, 0

    def handle(self, text: str) -> str:
        item, qty = find_item(text), _num(_QTY, text, int)
        weight, distance = _num(_KG, text, float), _num(_KM, text, float)
        if None in (item, qty, weight, distance):
            return "Sorry, I can only process a complete order (item, quantity, kg, km)."
        self.last_order = to_response(run_order(item, qty, weight, distance, verify_inventory=False,
                                                safe_commit=False, **self.flags))
        return self.last_order["message"] or self.last_order["status"]


class TA2:
    name = "TA2"

    def __init__(self, **flags):
        self.sup, self.hops = Supervisor("eval_customer", **flags), 0

    @property
    def last_order(self):
        return self.sup.last_order

    def handle(self, text: str) -> str:
        r = self.sup.handle(text)
        self.hops += len(r["hops"])
        return r["reply"]


def stock(store, item):
    return store.get_item(item)["stock"]


def status_of(sys):
    return sys.last_order["status"] if sys.last_order else None


# (name, messages in ONE conversation, flags, expected (text), check(system, final_reply, store) -> bool)
CASES = [
    ("1 Simple order", ["Order 5 wireless mouse, 1.2 kg, 15 km"], {},
     "confirmed, stock 42 -> 37",
     lambda s, r, st: status_of(s) == "confirmed" and stock(st, "wireless_mouse") == 37),
    ("2 Follow-up uses memory", ["Order 5 wireless mouse, 1.2 kg, 15 km", "Make it 3 instead"], {},
     "2nd order of 3 confirmed, stock 42 -> 34",
     lambda s, r, st: status_of(s) == "confirmed" and stock(st, "wireless_mouse") == 34),
    ("3 Policy question (RAG)", ["How long do I have to return an item?"], {},
     "answer says 14 days, cites 6.1",
     lambda s, r, st: "14 days" in r and "6.1" in r),
    ("4 Not in the policy", ["Does BudgetPost deliver on weekends?"], {},
     "\"I don't know\"",
     lambda s, r, st: "don't know" in r.lower()),
    ("5 Wrong inventory answer", ["Order 4 mechanical keyboard, 6 kg, 40 km"], {"inventory_fault": "overstate"},
     "declined (only 3 exist), stock stays 3",
     lambda s, r, st: status_of(s) == "declined" and stock(st, "mechanical_keyboard") == 3),
]


def run_case(system_cls, case):
    name, messages, flags, expected, check = case
    runner._APP = None
    store = use_store(Store.fresh())
    sys = system_cls(**flags)
    t0 = time.perf_counter()
    reply = ""
    for m in messages:
        reply = sys.handle(m)
    ms = (time.perf_counter() - t0) * 1000
    negative = sum(1 for r in store.list_inventory() if r["stock"] < 0)
    nodes = sum(len(store.list_checkpoints(o["thread_id"])) for o in store.list_orders())
    return {"case": name, "pass": bool(check(sys, reply, store)), "reply": reply.replace("\n", " / "),
            "ms": ms, "nodes": nodes, "hops": sys.hops, "corrupt": negative, "expected": expected}


def main():
    print("Engine:", runner.engine_name(), "| LLM enabled:", os.environ["ORDER_USE_LLM"] != "0")
    results = {cls.name: [run_case(cls, c) for c in CASES] for cls in (TA1, TA2)}

    for name, rows in results.items():
        print("\n" + "=" * 100)
        print(f" {name}")
        print("=" * 100)
        for r in rows:
            print(f" [{'PASS' if r['pass'] else 'FAIL'}] {r['case']:<26} expected: {r['expected']}")
            print(f"        got: {r['reply'][:150]}")

    print("\n" + "=" * 100)
    print(" PER-CASE COMPARISON")
    print("=" * 100)
    print(f" {'Case':<26} {'TA1':<6} {'TA2':<6} {'TA1 nodes':>9} {'TA2 nodes':>9} {'TA2 hops':>8} {'TA1 ms':>8} {'TA2 ms':>8}")
    for a, b in zip(results["TA1"], results["TA2"]):
        print(f" {a['case']:<26} {'PASS' if a['pass'] else 'FAIL':<6} {'PASS' if b['pass'] else 'FAIL':<6} "
              f"{a['nodes']:>9} {b['nodes']:>9} {b['hops']:>8} {a['ms']:>8.1f} {b['ms']:>8.1f}")

    print("\n" + "=" * 100)
    print(" SUMMARY")
    print("=" * 100)
    print(f" {'Metric':<40} {'TA1':>10} {'TA2':>10}")
    for label, fn in [
        ("Cases passed (of 5)", lambda rows: f"{sum(r['pass'] for r in rows)}/5"),
        ("Accuracy", lambda rows: f"{100 * sum(r['pass'] for r in rows) / len(rows):.0f}%"),
        ("Cases leaving negative stock", lambda rows: str(sum(r['corrupt'] > 0 for r in rows))),
        ("Graph nodes run (total)", lambda rows: str(sum(r['nodes'] for r in rows))),
        ("Supervisor hops (total)", lambda rows: str(sum(r['hops'] for r in rows))),
        ("Mean latency per case (ms)", lambda rows: f"{sum(r['ms'] for r in rows) / len(rows):.1f}"),
    ]:
        print(f" {label:<40} {fn(results['TA1']):>10} {fn(results['TA2']):>10}")


if __name__ == "__main__":
    main()
