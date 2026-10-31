from .states import OrderState, log
from .config import INVENTORY_DB
from .llm import call_local_llm


def check_inventory(state: OrderState) -> OrderState:
    item, qty = state["item"], state["requested_qty"]
    available = INVENTORY_DB.get(item, 0)
    state["available_qty"] = available
    state["inventory_ok"] = available >= qty
    log(state, "check_inventory",
        f"Requested {qty}x '{item}', found {available} in stock -> "
        f"{'SUFFICIENT' if state['inventory_ok'] else 'INSUFFICIENT'}")
    return state


def route_after_inventory(state: OrderState) -> str:
    return "proceed" if state["inventory_ok"] else "decline"


def calculate_shipping(state: OrderState) -> OrderState:
    weight, distance = state["weight_kg"], state["distance_km"]
    base_rate = 2.5
    distance_rate = 0.05
    cost = round(base_rate * weight + distance_rate * distance, 2)
    state["shipping_cost"] = cost
    log(state, "calculate_shipping",
        f"weight={weight}kg, distance={distance}km -> shipping_cost=${cost}")
    return state


def confirm_order(state: OrderState) -> OrderState:
    prompt = (
        "You are an order-fulfillment assistant. Write a short, friendly "
        "1-2 sentence confirmation message to the customer using ONLY these "
        f"facts: item={state['item']}, quantity={state['requested_qty']}, "
        f"shipping_cost=${state['shipping_cost']}. Do not invent any other details."
    )
    llm_reply = call_local_llm(prompt)
    if llm_reply:
        state["final_message"] = llm_reply
        log(state, "confirm_order", "LLM (qwen2.5:3b) generated confirmation message.")
    else:
        state["final_message"] = (
            f"Your order for {state['requested_qty']}x {state['item']} is CONFIRMED. "
            f"Estimated shipping cost: ${state['shipping_cost']}."
        )
        log(state, "confirm_order", "Ollama unavailable -> used deterministic fallback template.")
    return state


def decline_order(state: OrderState) -> OrderState:
    prompt = (
        "You are an order-fulfillment assistant. Write a short, polite 1-2 "
        "sentence message telling the customer their order cannot be fulfilled "
        f"right now, using ONLY these facts: item={state['item']}, "
        f"requested={state['requested_qty']}, available={state.get('available_qty', 0)}. "
        "Do not invent any other details."
    )
    llm_reply = call_local_llm(prompt)
    if llm_reply:
        state["final_message"] = llm_reply
        log(state, "decline_order", "LLM (qwen2.5:3b) generated decline message.")
    else:
        state["final_message"] = (
            f"Sorry, your order for {state['requested_qty']}x {state['item']} "
            f"cannot be fulfilled. Only {state.get('available_qty', 0)} unit(s) in stock."
        )
        log(state, "decline_order", "Ollama unavailable -> used deterministic fallback template.")
    return state
