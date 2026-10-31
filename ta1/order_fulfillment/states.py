from typing import TypedDict


class OrderState(TypedDict, total=False):
    item: str
    requested_qty: int
    available_qty: int
    weight_kg: float
    distance_km: float
    inventory_ok: bool
    shipping_cost: float
    final_message: str
    trace: list


def log(state: OrderState, node: str, note: str):
    state.setdefault("trace", []).append(f"[{node}] {note}")
