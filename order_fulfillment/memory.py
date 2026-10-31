"""Two kinds of memory for the conversational supervisor.

* ShortTermMemory - ONE conversation thread: the recent turns plus the order being discussed
  (item, qty, weight, distance, the order waiting for approval). Lives in RAM, so a restart wipes it.
* LongTermMemory  - per customer, in SQLite (table customer_memory): last item, usual distance,
  number of orders. Survives restarts.
"""
from .store import get_store


class ShortTermMemory:
    def __init__(self, window: int = 10):
        self.window = window
        self.turns = []          # [(role, text)], only the last `window` are kept
        self.slots = {}          # item, qty, weight_kg, distance_km, pending_thread

    def add_turn(self, role: str, text: str):
        self.turns.append((role, text))
        del self.turns[:-self.window]


class LongTermMemory:
    def __init__(self, customer: str):
        self.customer = customer

    def recall(self) -> dict:
        return get_store().recall(self.customer)

    def remember_order(self, item: str, weight_kg: float, distance_km: float):
        store, facts = get_store(), self.recall()
        store.remember(self.customer, "last_item", item)
        store.remember(self.customer, "last_weight_kg", weight_kg)
        store.remember(self.customer, "distance_km", distance_km)
        store.remember(self.customer, "orders_placed", facts.get("orders_placed", 0) + 1)
