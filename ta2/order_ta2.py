"""TA2: Order Fulfillment with thread + long-term memory, RAG, a supervisor over 5 agents, guard + human approval.
Stack: LangGraph (SqliteSaver, SqliteStore, interrupt), LangChain, Chroma, Ollama (qwen2.5:3b, nomic-embed-text)."""
import os, re, sqlite3
from functools import cache
from typing import TypedDict
from langchain_chroma import Chroma
from langchain_ollama import ChatOllama, OllamaEmbeddings
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import StateGraph, START, END
from langgraph.store.sqlite import SqliteStore
from langgraph.types import interrupt

HERE = os.path.dirname(os.path.abspath(__file__))
MAX_HOPS, THRESHOLD, MIN_SCORE = 8, 500.0, 0.45
SEED = {"wireless_mouse": (42, 25.0), "mechanical_keyboard": (3, 120.0), "usb_c_hub": (0, 40.0),
        "laptop": (5, 1200.0), "monitor": (10, 300.0)}                      # item: (stock, unit price)
STOCK = {k: v[0] for k, v in SEED.items()}                                  # authoritative stock
CACHE = dict(STOCK)                                    # inventory_agent's own copy (may be stale or wrong)
COURIERS = {"BudgetPost": (0, 2.5, .05, 30, 500, 5), "SpeedyExpress": (5, 4, .1, 50, 2000, 1),
            "EcoShip": (1.5, 2, .08, 15, 300, 4), "LocalBike": (0, 1.5, .2, 5, 20, 1)}  # base,/kg,/km,max kg,max km,days
LLM = ChatOllama(model="qwen2.5:3b", temperature=0)
RESET = {"status": "", "message": "", "claimed": None, "verified": False, "approval": "", "courier": "",
         "hops": 0, "max_hops": MAX_HOPS, "trace": [], "quote_tries": 0, "fail_quotes": 0, "llm_calls": 0}
class S(TypedDict, total=False):
    customer: str; request: str; item: str; qty: int; weight: float; distance: float; question: str; k: int
    claimed: int; verified: bool; approval: str; courier: str; price: float; eta: int; bids: dict; next: str
    status: str; message: str; hops: int; max_hops: int; trace: list; quote_tries: int; fail_quotes: int; llm_calls: int
def t(s, who, msg): return s.get("trace", []) + [f"[{who}] {msg}"]
def decline(s, who, why): return {"status": "declined", "trace": t(s, who, f"{why} -> DECLINED"),
                                   "message": f"Sorry, {s.get('qty')}x {s.get('item')} cannot be fulfilled: {why}."}
def supervisor(s: S, *, store) -> dict:
    """Decide who acts next with plain rules; recall the customer on 'reorder'; stop runaway loops."""
    hops, upd = s.get("hops", 0) + 1, {}
    if hops > s["max_hops"]:
        return {"hops": hops, "next": END, "status": "hop_limit", "message": "Stopped: hop limit reached.",
                "trace": t(s, "supervisor", f"hop {hops} > MAX_HOPS={s['max_hops']} -> hop_limit")}
    if s["request"] == "reorder":                                         # long-term memory: recall last order
        prof = store.get(("customers", s["customer"]), "profile")
        upd = {**prof.value, "request": "order"} if prof else {"status": "declined", "message": "No previous order."}
    s = {**s, **upd}                                                      # thread memory fills what is not given
    if s["request"] == "order" and not s["status"] and (miss := [f for f in ("item", "qty", "weight", "distance") if s.get(f) is None]):
        upd |= {"status": "need_info", "message": f"Please tell me: {', '.join(miss)}"}; s = {**s, **upd}
    nxt = (END if s["status"] else "policy_agent" if s["request"] == "question"
           else "inventory_agent" if s["claimed"] is None else "guard_agent" if not s["verified"]
           else "shipping_agent" if not s["courier"] else "guard_agent" if not s["approval"] else "order_agent")
    return {**upd, "hops": hops, "next": nxt, "trace": t(s, "supervisor", f"hop {hops} -> {nxt}")}
def inventory_agent(s: S) -> dict:
    """Report stock from its own cache. It can be wrong: the guard always checks it."""
    claimed = CACHE.get(s["item"], 0)
    return {"claimed": claimed, "trace": t(s, "inventory_agent", f"claims {claimed} x {s['item']} in stock")}
def guard_agent(s: S) -> dict:
    """1st visit: verify the claim against the real stock. 2nd visit: human approval if goods value >= $500."""
    item, qty = s["item"], s["qty"]
    if not s["verified"]:
        if not isinstance(qty, int) or qty < 1 or item not in STOCK:
            return decline(s, "guard_agent", f"invalid order (item={item}, qty={qty})")
        real = STOCK[item]; note = f"DISCREPANCY: claim {s['claimed']} but store has {real}; " if real != s["claimed"] else ""
        if real < qty: return decline(s, "guard_agent", f"{note}only {real} in stock")
        return {"verified": True, "trace": t(s, "guard_agent", f"{note}verified {real} >= {qty}")}
    if (value := qty * SEED[item][1]) < THRESHOLD:
        return {"approval": "auto", "trace": t(s, "guard_agent", f"goods ${value:.2f} < ${THRESHOLD:.0f} -> auto-approved")}
    decision = interrupt(  # PAUSE: state saved by the checkpointer until a human resumes with approved/rejected
        {"order": f"{qty}x {item}", "value": value, "courier": s["courier"], "shipping": s["price"]})
    if decision != "approved": return decline(s, "guard_agent", f"${value:.2f} order rejected by approver")
    return {"approval": "approved", "trace": t(s, "guard_agent", f"${value:.2f} >= ${THRESHOLD:.0f} -> APPROVED by human")}
def shipping_agent(s: S) -> dict:
    """Contract-net: every courier bids or refuses; the cheapest eligible bid wins. Quote failures retried once."""
    w, d, tries = s["weight"], s["distance"], s["quote_tries"] + 1
    try:
        if tries <= s["fail_quotes"]:                                     # injected tool failure for the demo
            raise TimeoutError("courier quote tool timed out")
        bids = {n: round(b + kg * w + km * d, 2) for n, (b, kg, km, mkg, mkm, _) in COURIERS.items() if w <= mkg and d <= mkm}
    except TimeoutError as e:
        if tries < 2:
            return {"quote_tries": tries, "trace": t(s, "shipping_agent", f"{e} (attempt {tries}) -> retrying once")}
        return {"quote_tries": tries, "status": "failed", "trace": t(s, "shipping_agent", f"{e} again -> FAILED, state saved"),
                "message": "Our courier price service is not responding. Nothing was charged; your order is saved and can be resumed."}
    if not bids: return decline(s, "shipping_agent", f"no courier can carry {w}kg over {d}km")
    win = min(bids, key=lambda n: (bids[n], COURIERS[n][5], n))           # cheapest, then faster, then name
    return {"courier": win, "price": bids[win], "eta": COURIERS[win][5], "bids": bids, "trace": t(s, "shipping_agent",
            f"bids {bids}, refused {[n for n in COURIERS if n not in bids]} -> {win} wins at ${bids[win]:.2f}")}
def order_agent(s: S, *, store) -> dict:
    """The only agent that changes stock. Saves the order to long-term memory and writes the message."""
    STOCK[s["item"]] -= s["qty"]; CACHE[s["item"]] = STOCK[s["item"]]
    store.put(("customers", s["customer"]), "profile", {k: s[k] for k in ("item", "qty", "weight", "distance")})
    facts = f"{s['qty']}x {s['item']}, courier {s['courier']}, {s['eta']} day(s), shipping ${s['price']:.2f}"
    try: msg = LLM.invoke(f"Write a 1-2 sentence order confirmation using ONLY these facts: {facts}.").content
    except Exception: msg = ""                                            # Ollama down -> template below
    writer = "LLM" if f"{s['price']:.2f}" in msg else "template"          # LLM must state the real price
    return {"status": "confirmed", "message": msg if writer == "LLM" else f"Order confirmed: {facts}.",
            "llm_calls": s["llm_calls"] + 1, "trace": t(s, "order_agent", f"stock {s['item']} -> {STOCK[s['item']]}, profile saved, message by {writer}")}
@cache
def policy_db():                                                          # one chunk per numbered policy clause
    db = Chroma("policy", OllamaEmbeddings(model="nomic-embed-text"), persist_directory=os.path.join(HERE, "chroma_db"),
                collection_metadata={"hnsw:space": "cosine"})
    if not db.get()["ids"]:                                               # embed once, then reuse from disk
        cl = re.findall(r"\*\*(\d+\.\d+) (.+?)\.\*\* (.+)", open(os.path.join(HERE, "shipping_policy.md"), encoding="utf-8").read())
        db.add_texts([f"{ti}. {b}" for _, ti, b in cl], [{"id": i} for i, _, _ in cl], ids=[i for i, _, _ in cl])
    return db
def policy_agent(s: S) -> dict:
    """Answer ONLY from retrieved policy clauses and cite the clause id, else say I don't know."""
    hits = [(d, sc) for d, sc in policy_db().similarity_search_with_relevance_scores(s["question"], k=s.get("k", 3)) if sc >= MIN_SCORE]
    ctx = "\n".join(f"[{d.metadata['id']}] {d.page_content}" for d, _ in hits)
    reply = LLM.invoke(f"Policy clauses:\n{ctx}\n\nQuestion: {s['question']}\nAnswer with one full sentence that states the fact "
                       "from the clauses above, then the clause id in square brackets, e.g. \"Returns are accepted within 14 days "
                       "[6.1].\" If no clause answers the question, reply exactly: I don't know").content if hits else ""
    if "don't know" in reply.lower() or not any(f"[{d.metadata['id']}]" in reply for d, _ in hits):
        reply = "I don't know - the shipping policy does not cover that."  # grounding check: must cite a retrieved clause
    return {"status": "answered", "message": reply, "llm_calls": s["llm_calls"] + bool(hits),
            "trace": t(s, "policy_agent", f"retrieved {[(d.metadata['id'], round(sc, 2)) for d, sc in hits]} -> {reply[:60]}")}
def build(prefix=os.path.join(HERE, "ta2")):
    g = StateGraph(S)
    g.add_node("supervisor", supervisor)
    for a in (inventory_agent, guard_agent, shipping_agent, order_agent, policy_agent):
        g.add_node(a.__name__, a); g.add_edge(a.__name__, "supervisor")     # control returns to the supervisor
    g.add_edge(START, "supervisor"); g.add_conditional_edges("supervisor", lambda s: s["next"])
    store = SqliteStore(sqlite3.connect(f"{prefix}_store.db", check_same_thread=False, isolation_level=None))
    store.setup()                                                         # long-term memory, per customer
    threads = SqliteSaver(sqlite3.connect(f"{prefix}_threads.db", check_same_thread=False))  # short-term, per thread
    return g.compile(checkpointer=threads, store=store)
