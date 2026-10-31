from .states import OrderState, log
from .config import APPROVAL_THRESHOLD
from .llm import call_local_llm, model_name
from .store import get_store
from .agents import InventoryAgent, ShippingAgent, OrderAgent
from .rag import get_index


def _valid_qty(q) -> bool:
    return isinstance(q, int) and not isinstance(q, bool) and q > 0


def _mentions(reply: str, *numbers) -> bool:
    return all(any(s in reply for s in n) for n in numbers)


# --------------------------------------------------------------------------
# Node 1: check_inventory  (Inventory agent answers; Order agent verifies;
#                           this is the ONLY place the proceed/decline decision is made)
# --------------------------------------------------------------------------
def check_inventory(state: OrderState) -> OrderState:
    store = get_store()
    item, qty = state["item"], state["requested_qty"]
    state.setdefault("approval", "")

    if not _valid_qty(qty):
        row = store.get_item(item)
        state.update(available_qty=row["stock"] if row else 0, inventory_ok=False,
                     decline_reason="invalid_quantity", route="decline", order_value=0.0)
        log(state, "check_inventory",
            f"Quantity {qty!r} is not a positive integer -> INVALID "
            f"(inventory_ok=False); ROUTE -> decline_order")
        return state

    rep = InventoryAgent(store, state.get("inventory_fault", "")).report(item, qty)
    claimed = rep["claimed_qty"]
    state["agent_claimed_qty"] = claimed
    available = claimed
    unverified = ""

    if state.get("verify_inventory", True):
        row = store.get_item(item)
        verified = row["stock"] if row else 0
        state["verified_qty"] = verified
        if verified != claimed:
            log(state, "check_inventory",
                f"DISCREPANCY: Inventory agent claimed {claimed} ({rep['source']}) but the "
                f"authoritative store has {verified} -> using the store value")
            available = verified
    else:
        unverified = f" [UNVERIFIED claim from Inventory agent, source={rep['source']}]"

    ok = rep["known"] and available >= qty
    state["available_qty"] = available
    state["inventory_ok"] = ok
    state["route"] = "proceed" if ok else "decline"
    state["unit_price"] = rep["unit_price"]
    state["order_value"] = round(qty * rep["unit_price"], 2) if ok else 0.0
    if not ok:
        state["decline_reason"] = ("unknown_item" if not rep["known"]
                                   else "out_of_stock" if available == 0
                                   else "insufficient_stock")

    nxt = "calculate_shipping" if ok else "decline_order"
    log(state, "check_inventory",
        f"Requested {qty}x '{item}', found {available} in stock -> "
        f"{'SUFFICIENT' if ok else 'INSUFFICIENT'} (inventory_ok={ok}); ROUTE -> {nxt}{unverified}")
    return state


def route_after_inventory(state: OrderState) -> str:
    """Conditional-edge function (read-only: LangGraph does not persist state changes made here)."""
    return state["route"]


# --------------------------------------------------------------------------
# Node 2: calculate_shipping = Shipping agent runs the contract-net auction
# --------------------------------------------------------------------------
def calculate_shipping(state: OrderState) -> OrderState:
    weight, distance = state["weight_kg"], state["distance_km"]
    bids, winner = ShippingAgent().call_for_proposals(weight, distance)
    state["bids"] = bids
    n_bid = sum(1 for b in bids if b["status"] == "BID")
    log(state, "calculate_shipping",
        f"Call for proposals: weight={weight}kg, distance={distance}km -> "
        f"{len(bids)} couriers invited, {n_bid} bids, {len(bids) - n_bid} refusals")
    for b in bids:
        if b["status"] == "BID":
            log(state, "calculate_shipping", f"  bid    {b['courier']:<14} ${b['price']:<8.2f} {b['eta_days']} day(s)")
        else:
            log(state, "calculate_shipping", f"  refuse {b['courier']:<14} ({b['reason']})")
    if winner:
        state.update(courier=winner["courier"], eta_days=winner["eta_days"], shipping_cost=winner["price"])
        log(state, "calculate_shipping",
            f"AWARD -> {winner['courier']} at ${winner['price']:.2f} (cheapest eligible bid)")
    else:
        state["decline_reason"] = "no_courier_available"
        log(state, "calculate_shipping", "No eligible courier -> ROUTE -> decline_order")
    return state


def route_after_shipping(state: OrderState) -> str:
    return "awarded" if state.get("courier") else "none"


# --------------------------------------------------------------------------
# Node 3: policy_lookup = RAG over shipping_policy.md (retrieval + citation)
# --------------------------------------------------------------------------
def policy_lookup(state: OrderState) -> OrderState:
    query = f"{state['courier']} courier eligibility delivery time"
    if state.get("order_value", 0) >= APPROVAL_THRESHOLD:
        query += " high-value order human approval threshold"
    hits = get_index().retrieve(query, 2)
    state["policy_refs"] = [h["id"] for h in hits]
    shown = ", ".join(f"§{h['id']} '{h['title']}' (score {h['score']})" for h in hits) or "nothing relevant"
    log(state, "policy_lookup", f"Query '{query}' -> retrieved {shown}")
    return state


# --------------------------------------------------------------------------
# Node 4: human_approval = high-value rule + pause/resume
# --------------------------------------------------------------------------
def human_approval(state: OrderState) -> OrderState:
    value = state.get("order_value", 0.0)
    needs = value >= APPROVAL_THRESHOLD
    state["approval_required"] = needs
    if not needs:
        state["approval"], state["approver"] = "approved", "auto (below threshold)"
        log(state, "human_approval",
            f"Goods value ${value:.2f} < ${APPROVAL_THRESHOLD:.2f} threshold -> auto-approved")
        return state

    decision = state.get("approval")
    if decision in ("approved", "rejected"):
        if decision == "rejected":
            state["decline_reason"] = "rejected_by_approver"
        log(state, "human_approval",
            f"Goods value ${value:.2f} >= ${APPROVAL_THRESHOLD:.2f}: human decision received -> "
            f"{decision.upper()} by {state.get('approver', 'approver')}")
        return state

    state["approval"], state["status"] = "pending", "awaiting_approval"
    OrderAgent(get_store()).record(state, "awaiting_approval")
    log(state, "human_approval",
        f"Goods value ${value:.2f} >= ${APPROVAL_THRESHOLD:.2f} threshold -> PAUSED, waiting for a human "
        f"(stock on hand per Inventory agent: {state.get('available_qty')}; courier {state['courier']} "
        f"${state['shipping_cost']:.2f}). Nothing is deducted yet.")
    return state


def route_after_approval(state: OrderState) -> str:
    return state.get("approval") or "pending"      # approved | rejected | pending


# --------------------------------------------------------------------------
# Node 5: confirm_order = Order agent commits (atomic stock decrement + courier booking)
# --------------------------------------------------------------------------
def confirm_order(state: OrderState) -> OrderState:
    agent = OrderAgent(get_store())
    if not agent.commit(state):
        state["commit_ok"], state["decline_reason"] = False, "commit_failed"
        log(state, "confirm_order",
            "COMMIT REFUSED: the guarded stock update found less stock than requested "
            "(stock changed since the check) -> ROUTE -> decline_order")
        return state

    state["commit_ok"], state["status"] = True, "confirmed"
    cost = state["shipping_cost"]
    prompt = (
        "You are an order-fulfillment assistant. Write a short, friendly "
        "1-2 sentence confirmation message to the customer using ONLY these "
        f"facts: item={state['item']}, quantity={state['requested_qty']}, courier={state['courier']}, "
        f"delivery_days={state['eta_days']}, shipping_cost=${cost:.2f}. Do not invent any other details."
    )
    reply = call_local_llm(prompt)
    if reply and _mentions(reply, (f"{cost:.2f}", str(cost))):
        msg, state["llm_used"] = reply, True
        log(state, "confirm_order",
            f"Committed (stock deducted atomically, {state['courier']} booked, {state['tracking_ref']}). "
            f"LLM ({model_name()}) wrote the message; grounding check passed.")
    else:
        why = ("LLM reply failed grounding check (shipping cost missing)" if reply
               else "Ollama unavailable/disabled")
        msg = (f"Your order for {state['requested_qty']}x {state['item']} is CONFIRMED. "
               f"Courier: {state['courier']} ({state['eta_days']} business day(s)), "
               f"shipping ${cost:.2f}. Tracking: {state['tracking_ref']}.")
        state["llm_used"] = False
        log(state, "confirm_order",
            f"Committed (stock deducted atomically, {state['courier']} booked, {state['tracking_ref']}). "
            f"{why} -> used deterministic template.")
    if state.get("policy_refs"):
        msg += " Policy: " + ", ".join(f"§{r}" for r in state["policy_refs"]) + "."
    state["final_message"] = msg
    return state


def route_after_confirm(state: OrderState) -> str:
    return "committed" if state.get("commit_ok") else "failed"


# --------------------------------------------------------------------------
# Node 6: decline_order
# --------------------------------------------------------------------------
_FIXED = {
    "unknown_item": "Sorry, we do not stock '{item}'.",
    "invalid_quantity": "Sorry, the requested quantity ({qty}) is not valid. Please enter a whole number of at least 1.",
    "no_courier_available": "Sorry, no courier can carry this parcel ({weight}kg over {distance}km).",
    "rejected_by_approver": "Your order for {qty}x {item} was reviewed and NOT approved.",
    "commit_failed": "Sorry, the stock for {qty}x {item} was no longer available at confirmation. Nothing was charged.",
}


def decline_order(state: OrderState) -> OrderState:
    reason = state.get("decline_reason", "insufficient_stock")
    qty, item = state["requested_qty"], state["item"]
    avail = state.get("available_qty", 0)
    state["status"] = "declined"
    OrderAgent(get_store()).record(state, "declined", reason)

    if reason in ("insufficient_stock", "out_of_stock"):
        prompt = (
            "You are an order-fulfillment assistant. Write a short, polite 1-2 "
            "sentence message telling the customer their order cannot be fulfilled "
            f"right now, using ONLY these facts: item={item}, requested={qty}, "
            f"available={avail}. Do not invent any other details."
        )
        reply = call_local_llm(prompt)
        if reply and _mentions(reply, (str(avail),)):
            state["final_message"], state["llm_used"] = reply, True
            log(state, "decline_order",
                f"reason={reason}. LLM ({model_name()}) wrote the message; grounding check passed. Order logged in SQLite.")
            return state
        why = ("LLM reply failed grounding check (stock number missing)" if reply
               else "Ollama unavailable/disabled")
        state["final_message"] = (f"Sorry, your order for {qty}x {item} cannot be fulfilled. "
                                  f"Only {avail} unit(s) in stock.")
        state["llm_used"] = False
        log(state, "decline_order", f"reason={reason}. {why} -> used deterministic template. Order logged in SQLite.")
        return state

    state["final_message"] = _FIXED.get(reason, "Sorry, your order cannot be fulfilled.").format(
        item=item, qty=qty, weight=state.get("weight_kg"), distance=state.get("distance_km"))
    state["llm_used"] = False
    log(state, "decline_order", f"reason={reason}. Fixed template used (no LLM needed). Order logged in SQLite.")
    return state
