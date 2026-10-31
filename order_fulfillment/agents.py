"""The four agents of Unit 4 (coordinated by supervisor.Supervisor).

* InventoryAgent - answers "do we have N of X?"  (can be made to answer WRONGLY for the demo)
* ShippingAgent  - runs the contract-net auction between couriers
* OrderAgent     - owns the order ledger: approval bookkeeping and the stock commit
* PolicyAgent    - answers shipping-policy questions from the policy document only (RAG)
"""
from .couriers import COURIERS
from .rag import ask_policy
from .store import Store


class InventoryAgent:
    def __init__(self, store: Store, fault: str = ""):
        self.store, self.fault = store, fault

    def report(self, item: str, qty: int) -> dict:
        row = self.store.get_item(item)
        if row is None:
            return {"known": False, "claimed_qty": 0, "unit_price": 0.0, "source": "store"}
        claimed = row["stock"]
        source = "store"
        if self.fault == "overstate":          # simulated stale cache / hallucinating agent
            claimed, source = row["stock"] + 100, "STALE-CACHE (faulty)"
        return {"known": True, "claimed_qty": claimed, "unit_price": row["unit_price"], "source": source}


class ShippingAgent:
    """Contract-net: broadcast a call for proposals, collect bids/refusals, award cheapest."""

    def __init__(self, couriers=COURIERS):
        self.couriers = couriers

    def call_for_proposals(self, weight_kg: float, distance_km: float):
        bids = []
        for c in self.couriers:
            problem = c.eligibility_problem(weight_kg, distance_km)
            if problem:
                bids.append({"courier": c.name, "status": "REFUSED", "price": None,
                             "eta_days": None, "reason": problem})
            else:
                bids.append({"courier": c.name, "status": "BID", "price": c.quote(weight_kg, distance_km),
                             "eta_days": c.eta_days, "reason": ""})
        eligible = [b for b in bids if b["status"] == "BID"]
        winner = min(eligible, key=lambda b: (b["price"], b["eta_days"], b["courier"])) if eligible else None
        for b in bids:
            b["winner"] = bool(winner and b["courier"] == winner["courier"])
        return bids, winner


class OrderAgent:
    def __init__(self, store: Store):
        self.store = store

    def record(self, state: dict, status: str, reason: str = None):
        self.store.upsert_order(
            state["thread_id"], item=state["item"], qty=state["requested_qty"],
            unit_price=state.get("unit_price"), order_value=state.get("order_value"),
            status=status, reason=reason, courier=state.get("courier"),
            shipping_cost=state.get("shipping_cost"), approval=state.get("approval"),
            approver=state.get("approver"))

    def commit(self, state: dict) -> bool:
        """Deduct stock + book the courier. Idempotent per thread_id (safe to retry after a crash)."""
        existing = self.store.get_order(state["thread_id"])
        if existing and existing["status"] == "confirmed":
            state["tracking_ref"] = f"TRK-{state['thread_id'][:6].upper()}"
            return True
        item, qty = state["item"], state["requested_qty"]
        ok = (self.store.reserve_stock(item, qty) if state.get("safe_commit", True)
              else self.store.force_decrement(item, qty))
        if not ok:
            return False
        state["tracking_ref"] = self.store.book_shipment(
            state["thread_id"], state["courier"], state["shipping_cost"], state["eta_days"])
        self.record(state, "confirmed")
        return True


class PolicyAgent:
    """RAG over shipping_policy.md; says "I don't know" when the policy does not cover the question."""

    def answer(self, question: str) -> dict:
        return ask_policy(question)
