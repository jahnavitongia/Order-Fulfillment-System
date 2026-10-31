"""Supervisor: routes a customer's chat message to the worker agents, one hop at a time.

    sup = Supervisor(customer="alice", max_hops=4)
    sup.handle("Do you have 3 monitors? How long do I have to return an item?")

Every sentence of a message becomes one task, and every task handed to an agent is one HOP.
After `max_hops` hops the supervisor STOPS and says which tasks it did not get to, so a
runaway request (or a future LLM router that keeps bouncing between agents) cannot loop forever.
Routing is deterministic rules, not an LLM, so it is auditable and testable.

Workers: inventory (stock questions), shipping (quotes), policy (RAG), order (place / approve,
which runs the LangGraph workflow). Memory: short-term (this conversation, RAM) fills in
what a follow-up leaves out ("make it 3 instead"); long-term (SQLite) remembers the customer.
"""
import re

from .agents import InventoryAgent, ShippingAgent, PolicyAgent
from .memory import ShortTermMemory, LongTermMemory
from .runner import run_order, approve_order, to_response
from .store import get_store

ALIASES = {"mouse": "wireless_mouse", "mice": "wireless_mouse", "keyboard": "mechanical_keyboard",
           "hub": "usb_c_hub", "laptop": "laptop", "monitor": "monitor"}
AGENT_OF = {"order": "order", "approval": "order", "inventory": "inventory",
            "shipping": "shipping", "policy": "policy"}

_KG = re.compile(r"(\d+(?:\.\d+)?)\s*kg")
_KM = re.compile(r"(\d+(?:\.\d+)?)\s*km")
_QTY = re.compile(r"(?<![\d.])(\d+)(?![\d.]|\s*(?:kg|km))")
_THREAD = re.compile(r"\b([0-9a-f]{8})\b")


def _num(rx, text, cast):
    m = rx.search(text.lower())
    return cast(m.group(1)) if m else None


def _first(*values):
    return next((v for v in values if v is not None), None)


def find_item(text: str):
    t = text.lower()
    for sku in (r["item"] for r in get_store().list_inventory()):
        if sku in t or sku.replace("_", " ") in t:
            return sku
    for word, sku in ALIASES.items():
        if re.search(rf"\b{word}e?s?\b", t):
            return sku
    return None


def split_sentences(text: str):
    return [s.strip() for s in re.split(r"(?<=[?!;])\s+|(?<=\.)\s+", text) if s.strip()]


def classify(sentence: str) -> str:
    t = sentence.lower()
    has_target = find_item(t) is not None or _num(_QTY, t, int) is not None
    if re.search(r"\b(approve|reject)\b", t) and not t.endswith("?"):
        return "approval"
    if has_target and re.search(r"\b(order|buy|purchase|make it|instead|i want|i'd like|send me)\b", t):
        return "order"
    if find_item(t) and re.search(r"\b(in stock|do you have|how many|available)\b", t):
        return "inventory"
    if re.search(r"\b(quote|shipping cost|cost to ship|how much .*ship)", t):
        return "shipping"
    return "policy"


class Supervisor:
    def __init__(self, customer: str = "guest", max_hops: int = 4, **order_flags):
        self.customer, self.max_hops, self.flags = customer, max_hops, order_flags
        self.short = ShortTermMemory()
        self.long = LongTermMemory(customer)
        self.last_order = None

    # ------------------------------------------------------------ main loop
    def handle(self, text: str) -> dict:
        self.short.add_turn("user", text)
        tasks = [(classify(s), s) for s in split_sentences(text)]
        hops, replies, stopped = [], [], False
        for i, (intent, sentence) in enumerate(tasks):
            if len(hops) >= self.max_hops:
                stopped = True
                replies.append(f"[supervisor] Stopped: reached the maximum of {self.max_hops} hop(s). "
                               f"Not handled: {' | '.join(s for _, s in tasks[i:])}")
                break
            reply = getattr(self, f"_{intent}")(sentence)
            hops.append({"hop": len(hops) + 1, "agent": AGENT_OF[intent], "intent": intent,
                         "task": sentence, "reply": reply})
            replies.append(reply)
        answer = "\n".join(replies)
        self.short.add_turn("assistant", answer)
        return {"reply": answer, "hops": hops, "stopped_by_max_hops": stopped,
                "short_term": dict(self.short.slots), "long_term": self.long.recall()}

    # ------------------------------------------------------------ workers
    def _order(self, sentence: str) -> str:
        s, lt = self.short.slots, self.long.recall()
        item = _first(find_item(sentence), s.get("item"), lt.get("last_item"))
        qty = _first(_num(_QTY, sentence, int), s.get("qty"))
        weight = _first(_num(_KG, sentence, float), s.get("weight_kg"), lt.get("last_weight_kg"))
        distance = _first(_num(_KM, sentence, float), s.get("distance_km"), lt.get("distance_km"))
        missing = [name for name, v in (("item", item), ("quantity", qty), ("weight in kg", weight),
                                        ("distance in km", distance)) if v is None]
        if missing:
            return "To place the order I still need: " + ", ".join(missing) + "."
        s.update(item=item, qty=qty, weight_kg=weight, distance_km=distance)

        r = self.last_order = to_response(run_order(item, qty, weight, distance, **self.flags))
        if r["status"] == "awaiting_approval":
            s["pending_thread"] = r["thread_id"]
            return (f"Order {r['thread_id']}: {qty}x {item} worth ${r['order_value']:.2f} needs a manager's "
                    f"approval ({r['courier']}, shipping ${r['shipping_cost']:.2f}). Reply 'approve' or 'reject'.")
        if r["status"] == "confirmed":
            self.long.remember_order(item, weight, distance)
        return r["message"]

    def _approval(self, sentence: str) -> str:
        m = _THREAD.search(sentence.lower())
        tid = m.group(1) if m else self.short.slots.get("pending_thread")
        if not tid:
            return "There is no order waiting for approval in this conversation."
        decision = "rejected" if re.search(r"\breject", sentence.lower()) else "approved"
        r = self.last_order = approve_order(tid, decision, approver="manager (chat)")
        self.short.slots.pop("pending_thread", None)
        if r["status"] == "confirmed":
            self.long.remember_order(r["item"], self.short.slots.get("weight_kg"),
                                     self.short.slots.get("distance_km"))
        return r["message"]

    def _inventory(self, sentence: str) -> str:
        item = _first(find_item(sentence), self.short.slots.get("item"))
        qty = _first(_num(_QTY, sentence, int), 1)
        rep = InventoryAgent(get_store()).report(item, qty)
        if not rep["known"]:
            return f"Sorry, we do not stock '{item}'."
        self.short.slots["item"] = item
        have = rep["claimed_qty"]
        return (f"{'Yes' if have >= qty else 'No'}: {have} {item} in stock "
                f"(${rep['unit_price']:.2f} each), you asked about {qty}.")

    def _shipping(self, sentence: str) -> str:
        s = self.short.slots
        weight = _first(_num(_KG, sentence, float), s.get("weight_kg"))
        distance = _first(_num(_KM, sentence, float), s.get("distance_km"), self.long.recall().get("distance_km"))
        if weight is None or distance is None:
            return "For a quote I need the weight (kg) and distance (km)."
        bids, win = ShippingAgent().call_for_proposals(weight, distance)
        if not win:
            return f"No courier can carry {weight}kg over {distance}km."
        return (f"Cheapest quote: {win['courier']} ${win['price']:.2f}, {win['eta_days']} day(s) "
                f"({sum(b['status'] == 'BID' for b in bids)} bids, {sum(b['status'] == 'REFUSED' for b in bids)} refused).")

    def _policy(self, sentence: str) -> str:
        return PolicyAgent().answer(sentence)["answer"]
