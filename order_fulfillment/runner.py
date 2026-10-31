import json
import os
import uuid

from .graph_wrapper import (build_graph, LANGGRAPH_AVAILABLE, MERMAID, NODES, END,
                            SimulatedCrash, next_node)
from .states import OrderState, note
from .llm import model_name
from .store import Store, get_store, use_store
from .agents import OrderAgent
from .config import APPROVAL_THRESHOLD

_APP = None

NODE_NOTES = {
    "check_inventory": "Inventory agent answers, Order agent verifies against the store; decides the route.",
    "calculate_shipping": "Shipping agent's contract-net auction. Runs ONLY on the 'proceed' branch.",
    "policy_lookup": "RAG: retrieves the relevant shipping-policy clauses (BM25) to cite in the result.",
    "human_approval": f"High-value rule: goods value >= ${APPROVAL_THRESHOLD:.2f} pauses for a human decision.",
    "confirm_order": "Order agent commits: atomic guarded stock decrement + courier booking, then LLM phrases the message.",
    "decline_order": "Terminal failure node, reached only through a conditional edge. Logs the order in SQLite.",
}


def get_app():
    global _APP
    if _APP is None:
        _APP = build_graph()
    return _APP


def engine_name() -> str:
    return "REAL langgraph package" if LANGGRAPH_AVAILABLE else "fallback mini-graph (pip install langgraph)"


# ------------------------------------------------------------------ core API
def run_order(item, requested_qty, weight_kg, distance_km, thread_id=None, **flags) -> OrderState:
    """Start a new order. flags: verify_inventory, safe_commit, inventory_fault, crash_after."""
    initial: OrderState = {
        "thread_id": thread_id or uuid.uuid4().hex[:8],
        "item": item, "requested_qty": requested_qty,
        "weight_kg": weight_kg, "distance_km": distance_km,
        "verify_inventory": flags.get("verify_inventory", True),
        "safe_commit": flags.get("safe_commit", True),
        "inventory_fault": flags.get("inventory_fault", ""),
        "crash_after": flags.get("crash_after", ""),
        "trace": [], "path": [],
    }
    try:
        return get_app().invoke(initial)
    except SimulatedCrash as e:
        store = get_store()
        ck = store.latest_checkpoint(initial["thread_id"])
        state = ck["state"]
        state["status"] = "interrupted"
        OrderAgent(store).record(state, "interrupted")
        note(state, f"[CRASH] {e}. Progress is safe in SQLite (checkpoint step {ck['step']}).")
        return state


def resume_order(thread_id: str, approval: str = None, approver: str = "human approver") -> OrderState:
    """Resume from the latest SQLite checkpoint, optionally supplying the human's decision."""
    store = get_store()
    ck = store.latest_checkpoint(thread_id)
    if ck is None:
        raise ValueError(f"No checkpoint for thread '{thread_id}'")
    state, last = ck["state"], ck["node"]
    state["crash_after"] = ""

    if state.get("status") in ("confirmed", "declined"):
        note(state, f"[resume] Order already finished ({state['status']}); nothing to do.")
        return state

    if state.get("approval") == "pending":
        if approval not in ("approved", "rejected"):
            note(state, "[resume] Still waiting for a human decision (approved/rejected).")
            return state
        state.update(approval=approval, approver=approver, status="")
        target = "human_approval"
    else:
        target = next_node(last, state)
        if target == END:
            return state

    state["resume_from"] = target
    note(state, f"[resume] Loaded checkpoint step {ck['step']} (after '{last}') from SQLite; "
                f"continuing at '{target}'. Earlier nodes are NOT re-run.")
    final = get_app().invoke(state)
    final["resume_from"] = ""
    return final


# ------------------------------------------------------------------ API helpers
def to_response(final: dict) -> dict:
    status = final.get("status") or ("confirmed" if final.get("commit_ok") else "declined")
    resp = {
        "status": status,
        "thread_id": final["thread_id"],
        "item": final["item"],
        "requested_qty": final["requested_qty"],
        "stock": final.get("available_qty", 0),
        "message": final.get("final_message", ""),
        "trace": final["trace"],
        "path": final["path"],
        "llm_used": final.get("llm_used", False),
        "engine": "langgraph" if LANGGRAPH_AVAILABLE else "fallback",
        "order_value": final.get("order_value", 0.0),
        "approval_required": final.get("approval_required", False),
        "bids": final.get("bids", []),
        "courier": final.get("courier"),
        "eta_days": final.get("eta_days"),
        "policy_refs": final.get("policy_refs", []),
    }
    if status == "confirmed":
        resp["shipping_cost"] = final.get("shipping_cost")
        resp["tracking_ref"] = final.get("tracking_ref")
    if status == "declined":
        resp["reason"] = final.get("decline_reason")
    if status == "awaiting_approval":
        resp["shipping_cost"] = final.get("shipping_cost")
    return resp


def process_order(payload: dict) -> dict:
    """Used by the HTTP server. Raises ValueError on malformed input."""
    try:
        item = str(payload["item"]).strip()
        qty_raw = payload["requested_qty"]
        qty = int(qty_raw) if float(qty_raw) == int(float(qty_raw)) else qty_raw
        weight = float(payload["weight_kg"])
        distance = float(payload["distance_km"])
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError(f"Invalid order payload: {e!r}")
    if not item or weight < 0 or distance < 0:
        raise ValueError("item must be non-empty; weight_kg and distance_km must be >= 0")
    return to_response(run_order(item, qty, weight, distance))


def approve_order(thread_id: str, decision: str, approver: str = "human approver") -> dict:
    if decision not in ("approved", "rejected"):
        raise ValueError("decision must be 'approved' or 'rejected'")
    return to_response(resume_order(thread_id, decision, approver))


# ------------------------------------------------------------------ printing
def format_bid_table(bids) -> str:
    rows = ["  Courier         Status    Price     ETA     Result",
            "  --------------  --------  --------  ------  ------------------------------------"]
    for b in bids:
        price = f"${b['price']:.2f}" if b["price"] is not None else "-"
        eta = f"{b['eta_days']} d" if b["eta_days"] is not None else "-"
        result = "<< WINNER (cheapest eligible)" if b.get("winner") else (b["reason"] or "outbid")
        rows.append(f"  {b['courier']:<14}  {b['status']:<8}  {price:<8}  {eta:<6}  {result}")
    return "\n".join(rows)


def print_result(final: dict, show_state: bool = True):
    print("\n--- ANNOTATED EXECUTION TRACE ---")
    for i, step in enumerate(final["trace"], 1):
        print(f"  {i:>2}. {step}")
    if final.get("bids"):
        print("\n--- COURIER BID TABLE (contract-net) ---")
        print(format_bid_table(final["bids"]))
    print("\n  Node path :", " -> ".join(final["path"]))
    skipped = [n for n in NODES if n not in final["path"]]
    print("  Not run   :", ", ".join(skipped) or "(none)")
    print("\n  Why each node ran:")
    for n in dict.fromkeys(final["path"]):
        print(f"    - {n}: {NODE_NOTES[n]}")
    print("\n--- FINAL CUSTOMER-FACING MESSAGE ---")
    print(f"  [{final.get('status', '?').upper()}] {final.get('final_message', '(none yet)')}")
    print(f"  (message written by: {'LLM ' + model_name() if final.get('llm_used') else 'deterministic template'})")
    if show_state:
        print("\n--- RAW FINAL STATE (for jury inspection) ---")
        printable = {k: v for k, v in final.items() if k not in ("trace", "bids", "path")}
        print(json.dumps(printable, indent=2))


def run_case(title, item, requested_qty, weight_kg, distance_km, **flags):
    print("\n" + "=" * 78)
    print(f" CASE: {title}")
    print("=" * 78)
    print(f" INPUT: item={item!r}, qty={requested_qty!r}, weight={weight_kg}kg, distance={distance_km}km")
    final = run_order(item, requested_qty, weight_kg, distance_km, **flags)
    print_result(final)
    return final


def header():
    print("LangGraph backend:", engine_name())
    print("OLLAMA_HOST      :", os.environ.get("OLLAMA_HOST", "(not set, using default)"))
    print("OLLAMA_MODEL     :", model_name())
    print("LLM enabled      :", os.environ.get("ORDER_USE_LLM", "1") != "0")


def main():
    """Jury-1 style annotated traces (fresh seeded database every run)."""
    use_store(Store.fresh())
    header()
    print("\nGraph (Mermaid):\n" + MERMAID)

    run_case("A) Order that CAN be fulfilled (sufficient stock)", "wireless_mouse", 5, 1.2, 15)
    run_case("B) Order that CANNOT be fulfilled (insufficient stock: want 10, have 3)",
             "mechanical_keyboard", 10, 8.0, 40)
    run_case("C) Edge case: item completely out of stock (usb_c_hub = 0)", "usb_c_hub", 1, 0.3, 10)
    run_case("D) Edge case: invalid quantity (0)", "wireless_mouse", 0, 1.0, 10)

    print("\n" + "=" * 78)
    print(" Next: run  python jury2_demo.py  for the Unit 3 / Unit 4 evidence")
    print("=" * 78)


if __name__ == "__main__":
    main()
