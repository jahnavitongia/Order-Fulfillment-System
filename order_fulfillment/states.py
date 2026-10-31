from typing import TypedDict


class OrderState(TypedDict, total=False):
    # ---- input ----
    thread_id: str
    item: str
    requested_qty: int
    weight_kg: float
    distance_km: float
    # ---- test / demo switches ----
    verify_inventory: bool   # Order agent re-checks the Inventory agent's claim against the store
    safe_commit: bool        # stock is deducted with an atomic guarded UPDATE
    inventory_fault: str     # "" | "overstate"  (makes the Inventory agent give a WRONG answer)
    crash_after: str         # simulate a crash right after this node's checkpoint
    resume_from: str         # set by resume_order(); START jumps straight to this node
    # ---- inventory ----
    agent_claimed_qty: int
    verified_qty: int
    available_qty: int
    unit_price: float
    order_value: float
    inventory_ok: bool
    route: str               # "proceed" | "decline"
    decline_reason: str
    # ---- shipping auction ----
    bids: list
    courier: str
    eta_days: int
    shipping_cost: float
    # ---- policy RAG ----
    policy_refs: list
    # ---- approval ----
    approval_required: bool
    approval: str            # "" | "pending" | "approved" | "rejected"
    approver: str
    # ---- result ----
    commit_ok: bool
    tracking_ref: str
    status: str              # confirmed | declined | awaiting_approval | interrupted
    final_message: str
    llm_used: bool
    step: int
    path: list               # node names actually executed, in order
    trace: list              # human-readable annotated log lines


def log(state: OrderState, node: str, note: str):
    """Append an annotated line to the trace and record the node in `path`."""
    state.setdefault("trace", []).append(f"[{node}] {note}")
    path = state.setdefault("path", [])
    if not path or path[-1] != node:
        path.append(node)


def note(state: OrderState, text: str):
    """Trace line that is not a graph node (e.g. checkpoint / resume messages)."""
    state.setdefault("trace", []).append(text)
