"""Jury 2 evidence script (Unit 3 + Unit 4).  Run:

    python jury2_demo.py > jury2_evidence.txt

Every section uses a fresh, freshly-seeded SQLite database, so the output is repeatable.
"""
from order_fulfillment import runner
from order_fulfillment.store import Store, use_store
from order_fulfillment.runner import (run_order, resume_order, approve_order, print_result,
                                      format_bid_table, header)
from order_fulfillment.rag import ask_policy, get_index
from order_fulfillment.config import APPROVAL_THRESHOLD


def banner(text):
    print("\n" + "#" * 78)
    print(f"# {text}")
    print("#" * 78)


def sub(text):
    print("\n" + "=" * 78)
    print(f" {text}")
    print("=" * 78)


def new_db():
    runner._APP = None
    return use_store(Store.fresh())


def restart(store):
    """Simulate a process restart: new Store object on the same file + a freshly built graph."""
    runner._APP = None
    return use_store(Store(store.path))


def show_inventory(store, items=None):
    print("  inventory table:")
    for r in store.list_inventory():
        if not items or r["item"] in items:
            print(f"    {r['item']:<20} stock={r['stock']:<4} unit_price=${r['unit_price']:.2f}")


def show_orders(store):
    print("  orders table:")
    for r in store.list_orders():
        print(f"    {r['thread_id']}  {r['item']:<20} qty={r['qty']:<3} value=${r['order_value'] or 0:<8.2f} "
              f"status={r['status']:<18} courier={r['courier']} reason={r['reason']}")
    ships = store.list_shipments()
    print("  shipments table:", [(s['thread_id'], s['courier'], s['tracking_ref']) for s in ships] or "(empty)")


# ----------------------------------------------------------------------------------------
def unit3_sqlite():
    banner("UNIT 3 / EVIDENCE 1: SQLite as persistent inventory + order store")
    store = new_db()
    print("Fresh database created at:", store.path)
    show_inventory(store, ["wireless_mouse", "laptop"])
    r = run_order("wireless_mouse", 5, 1.2, 15)
    print(f"\nPlaced order {r['thread_id']}: 5x wireless_mouse -> {r['status']}")
    store = restart(store)
    print("\n-- 'restarting the program' (new connection, new graph object) --")
    show_inventory(store, ["wireless_mouse", "laptop"])
    show_orders(store)
    print("\n  -> stock went 42 -> 37 and the order + shipment survived the restart: the data lives in SQLite, not in memory.")


def unit3_checkpoint():
    banner("UNIT 3 / EVIDENCE 2: checkpointer - resume an interrupted order")
    store = new_db()
    sub("Step 1: start a laptop order but CRASH right after the courier auction")
    r = run_order("laptop", 1, 3.0, 120, crash_after="calculate_shipping")
    tid = r["thread_id"]
    for line in r["trace"]:
        print("  ", line)
    print("\n  checkpoints saved in SQLite:", [(c["step"], c["node"]) for c in store.list_checkpoints(tid)])
    print("  order row:", {k: store.get_order(tid)[k] for k in ("status", "courier")})
    show_inventory(store, ["laptop"])

    sub("Step 2: 'restart the program' and resume from the checkpoint (inventory is NOT re-checked)")
    store = restart(store)
    r2 = resume_order(tid)
    for line in r2["trace"][len(r["trace"]) - 1:]:
        print("  ", line)
    print("\n  status now:", r2["status"], "(laptop is >= $%.2f so it pauses for a human)" % APPROVAL_THRESHOLD)
    print("  check_inventory appears in the trace", sum(1 for l in r2["trace"] if l.startswith("[check_inventory]")),
          "time(s) -> it was not repeated after the resume.")

    sub("Step 3: restart AGAIN while waiting for approval, then approve")
    store = restart(store)
    r3 = approve_order(tid, "approved", approver="manager")
    for line in r3["trace"][len(r2["trace"]):]:
        print("  ", line)
    show_inventory(store, ["laptop"])
    show_orders(store)
    print("\n  -> stock was deducted exactly once (5 -> 4). The commit is idempotent per thread_id, so a retry cannot double-deduct.")


def unit3_rag():
    banner("UNIT 3 / EVIDENCE 3: RAG over shipping_policy.md")
    idx = get_index()
    print(f"Indexed {idx.N} policy clauses: {[c['id'] for c in idx.chunks]}")
    for q in ["Which courier can carry a 40 kg parcel?",
              "When do I need approval for an expensive order?",
              "How long do I have to return an item?"]:
        sub(f"Q: {q}")
        hits = idx.retrieve(q, 3)
        print("  retrieved:", [(h["id"], h["score"]) for h in hits])
        a = ask_policy(q)
        print("  answer :", a["answer"])
        print("  method :", a["method"], "| sources:", a["sources"])
    print("\n  Inside the workflow, the policy_lookup node runs the same retrieval and the confirmation cites the clauses (e.g. 'Policy: §1.1, §2.1').")


def unit4_bids():
    banner("UNIT 4 / EVIDENCE 1: contract-net bidding (cheapest eligible courier wins)")
    cases = [("Light parcel, short trip", "wireless_mouse", 1, 1.2, 15),
             ("Tiny local parcel", "wireless_mouse", 1, 2.0, 10),
             ("Heavy, long distance (only one courier is eligible)", "monitor", 2, 40.0, 800),
             ("Too heavy for everyone -> order declined", "monitor", 1, 80.0, 100)]
    for title, item, q, w, d in cases:
        new_db()
        sub(f"{title}: {w}kg over {d}km")
        r = run_order(item, q, w, d)
        print(format_bid_table(r["bids"]))
        print(f"  -> status={r['status']}  courier={r.get('courier')}  reason={r.get('decline_reason')}")
        if r["status"] == "awaiting_approval":
            print("     (monitor x2 = $600 is a high-value order, so it paused for approval after the auction)")


def unit4_approval():
    banner("UNIT 4 / EVIDENCE 2: human approval for high-value orders")
    print(f"Rule: goods value (qty x unit price, shipping excluded) >= ${APPROVAL_THRESHOLD:.2f} -> human must approve.")
    new_db()
    sub("a) $125 order (5 mice): below the threshold -> auto-approved")
    r = run_order("wireless_mouse", 5, 1.2, 15)
    print("  ", [l for l in r["trace"] if l.startswith("[human_approval]")][0])
    print("   status:", r["status"])

    sub("b) EXACTLY $500 (20 mice): the rule is >=, so it needs approval")
    r = run_order("wireless_mouse", 20, 5.0, 15)
    print("  ", [l for l in r["trace"] if l.startswith("[human_approval]")][0])
    print("   status:", r["status"])
    r = approve_order(r["thread_id"], "approved", "manager")
    print("   after approval ->", r["status"])

    sub("c) $1,200 laptop: paused, then APPROVED")
    r = run_order("laptop", 1, 3.0, 120)
    print("  ", [l for l in r["trace"] if l.startswith("[human_approval]")][0])
    print("   status:", r["status"], "| stock still", runner.get_store().get_item("laptop")["stock"], "(nothing deducted while waiting)")
    r = approve_order(r["thread_id"], "approved", "manager")
    print("  ", [l for l in r["trace"] if l.startswith("[human_approval]")][-1])
    print("   status:", r["status"], "| stock now", runner.get_store().get_item("laptop")["stock"])

    sub("d) $600 (2 monitors): paused, then REJECTED")
    r = run_order("monitor", 2, 12.0, 30)
    r = approve_order(r["thread_id"], "rejected", "manager")
    print_result(r, show_state=False)
    print("   monitor stock still", runner.get_store().get_item("monitor")["stock"])
    show_orders(runner.get_store())


def _scenario(label, verify, safe):
    store = new_db()
    r = run_order("mechanical_keyboard", 10, 8.0, 40,
                  inventory_fault="overstate", verify_inventory=verify, safe_commit=safe)
    claimed = r.get("agent_claimed_qty")
    asked_human = r["status"] == "awaiting_approval"
    if asked_human:
        r = approve_order(r["thread_id"], "approved", "manager")   # the human trusts what the system shows
    real = store.get_item("mechanical_keyboard")["stock"]
    order = store.get_order(r["thread_id"])
    return {"label": label, "trace": r["trace"], "claimed": claimed,
            "asked_human": asked_human, "status": r["status"], "stock_after": real,
            "ships": len(store.list_shipments()), "auction": "calculate_shipping" in r["path"],
            "order": order, "reason": r.get("decline_reason")}


def unit4_error_propagation():
    banner("UNIT 4 / EVIDENCE 3: error propagation - a WRONG inventory answer flows downstream")
    print("Setup: the store really has 3 mechanical_keyboards (unit price $120). The Inventory agent is made to\n"
          "answer WRONGLY (stale cache: claims 103). A customer orders 10 keyboards (worth $1,200).")
    results = [
        _scenario("A) NO FIX (trust the agent, unguarded stock update)", verify=False, safe=False),
        _scenario("B) PARTIAL FIX (commit guard only)", verify=False, safe=True),
        _scenario("C) FULL FIX (verify the claim + commit guard)", verify=True, safe=True),
    ]
    for s in results:
        sub(s["label"])
        for line in s["trace"]:
            print("  ", line)

    sub("DAMAGE REPORT (what the wrong answer caused downstream)")
    print(f"  {'Scenario':<10} {'Agent said':<11} {'Truth':<6} {'Courier':<8} {'Human':<9} {'Stock':<7} {'Order status':<11} Verdict")
    print(f"  {'-'*10} {'-'*11} {'-'*6} {'-'*8} {'-'*9} {'-'*7} {'-'*11} {'-'*40}")
    verdicts = ["OVERSOLD: sold 10, had 3, stock is negative, courier booked for goods that do not exist",
                "No oversell, but a courier auction + a manager's time were wasted on a bogus order",
                "Caught at step 1 (DISCREPANCY). No auction, no approval request, no damage"]
    for s, v in zip(results, verdicts):
        print(f"  {s['label'][0]:<10} {s['claimed']:<11} {3:<6} {'BOOKED' if s['ships'] else 'no':<8} "
              f"{'asked' if s['asked_human'] else 'not asked':<9} {s['stock_after']:<7} {s['status']:<11} {v}")
    print("\n  Where damage happened in A: (1) shipping auction ran on a fantasy quantity, (2) the approver was shown\n"
          "  'stock on hand: 103' and approved on false information, (3) the ledger was corrupted: stock = -7 and a\n"
          "  confirmed order + shipment exist for 7 units that never existed.\n"
          "  The fix has two layers: B stops the corruption at commit time (defense in depth); C stops the error\n"
          "  at its source, so no downstream agent ever acts on it.")


if __name__ == "__main__":
    header()
    unit3_sqlite()
    unit3_checkpoint()
    unit3_rag()
    unit4_bids()
    unit4_approval()
    unit4_error_propagation()
