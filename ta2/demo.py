"""Saved traces for every TA2 module (Ollama must be running).  Run from the project folder:

    python ta2/demo.py > traces/ta2_traces.txt
"""
import os, subprocess, sys, tempfile
from langgraph.types import Command
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from order_ta2 import build, RESET, SEED, STOCK, CACHE, policy_db, MAX_HOPS, THRESHOLD  # noqa: E402


def fresh(prefix=None):
    """New app with empty memory databases and full stock."""
    STOCK.update({k: v[0] for k, v in SEED.items()}); CACHE.clear(); CACHE.update(STOCK)
    return build(prefix or os.path.join(tempfile.mkdtemp(prefix="ta2_"), "ta2"))


def cfg(thread): return {"configurable": {"thread_id": thread}}
def ask(app, thread, customer="alice", **inp):
    """One customer turn. Only the fields that changed are needed; the thread remembers the rest."""
    return app.invoke({**RESET, "customer": customer, "request": "order", **inp}, cfg(thread))
def approve(app, thread, decision="approved"): return app.invoke(Command(resume=decision), cfg(thread))
def resume(app, thread):
    """Continue a failed order from its last checkpoint (earlier steps are not repeated)."""
    saved = app.get_state(cfg(thread)).values
    marker = f"[resume] loaded checkpoint of thread {thread}: claim + verification kept, continuing from shipping"
    return app.invoke({"status": "", "fail_quotes": 0, "quote_tries": 0, "hops": 0,
                       "trace": saved["trace"] + [marker]}, cfg(thread))


def show(title, r):
    print(f"\n--- {title}")
    for line in r.get("trace", []):
        print("   ", line)
    if "__interrupt__" in r:
        print("    PAUSED for human approval:", r["__interrupt__"][0].value)
    else:
        print(f"    => status={r.get('status')} | {r.get('message')}")


def banner(text): print("\n" + "=" * 90 + f"\n {text}\n" + "=" * 90)


if __name__ == "__main__":
    print(f"TA2 prototype | MAX_HOPS={MAX_HOPS} | approval threshold=${THRESHOLD:.0f} | qwen2.5:3b + nomic-embed-text")

    banner("U3-1 SHORT-TERM MEMORY: checkpointer + thread_id")
    app = fresh()
    show("thread A, turn 1: full order", ask(app, "A", item="wireless_mouse", qty=5, weight=1.2, distance=15))
    show("thread A, turn 2: only 'make it 3' (item, weight, distance come from the thread)", ask(app, "A", qty=3))
    show("thread B (new thread_id), same 'make it 3': AMNESIA, the new thread knows nothing", ask(app, "B", qty=3))

    banner("U3-2 LONG-TERM MEMORY: SqliteStore survives a restart")
    prefix = os.path.join(tempfile.mkdtemp(prefix="ta2_restart_"), "ta2")
    app = fresh(prefix)
    show("process 1: bob orders a monitor", ask(app, "bob-1", "bob", item="monitor", qty=1, weight=4, distance=60))
    print("\n--- program stopped. A NEW Python process starts and bob says only 'reorder' on a new thread:")
    code = (f"import sys; sys.path.insert(0, {os.path.dirname(os.path.abspath(__file__))!r}); import demo; "
            f"app = demo.fresh({prefix!r}); demo.show('process 2: reorder', demo.ask(app, 'bob-2', 'bob', request='reorder'))")
    print(subprocess.run([sys.executable, "-c", code], capture_output=True, text=True).stdout)

    banner("U3-3 RAG: Chroma + nomic-embed-text over shipping_policy.md")
    print(f"Chunks in Chroma: {len(policy_db().get()['ids'])} (one per numbered clause)")
    app = fresh()
    for q in ["Which courier can carry a 40 kg parcel?", "How long do I have to return an item?"]:
        for k in (1, 3):
            show(f"k={k}: {q}", ask(app, f"rag-{k}-{q}", request="question", question=q, k=k))
    show("paraphrase: 'expensive order' should reach clause 3.1",
         ask(app, "rag-para", request="question", question="Do I need permission for an expensive order?"))
    show("unanswerable: the agent must refuse", ask(app, "rag-no", request="question", question="Do you offer gift wrapping?"))

    banner("U3-4 TOOL FAILURE: courier quote tool times out")
    app = fresh()
    show("1 failure: caught, retried once, succeeds", ask(app, "F1", item="monitor", qty=1, weight=4, distance=60, fail_quotes=1))
    show("2 failures: caught, explained, nothing charged", ask(app, "F2", item="monitor", qty=1, weight=4, distance=60, fail_quotes=2))
    show("resume F2 from its checkpoint (inventory + guard are NOT repeated)", resume(app, "F2"))

    banner("U4-2 COORDINATION: courier bidding (contract-net) + hop limit")
    app = fresh()
    show("1.2 kg over 15 km", ask(app, "bid-1", item="wireless_mouse", qty=1, weight=1.2, distance=15))
    show("40 kg over 800 km: only one courier eligible", ask(app, "bid-2", item="monitor", qty=1, weight=40, distance=800))
    show("80 kg: every courier refuses", ask(app, "bid-3", item="monitor", qty=1, weight=80, distance=100))
    show("runaway guard: same order with max_hops=3", ask(app, "hops", item="monitor", qty=1, weight=4, distance=60, max_hops=3))

    banner("U4-3 OVERSIGHT: human approval with interrupt()")
    app = fresh()
    show("5 mice = $125", ask(app, "ap-1", item="wireless_mouse", qty=5, weight=1.2, distance=15))
    r = ask(app, "ap-2", item="wireless_mouse", qty=20, weight=5, distance=15)
    show("20 mice = $500 exactly (rule is inclusive)", r)
    print(f"    stock while waiting: {STOCK['wireless_mouse']} (nothing deducted)")
    show("human APPROVES", approve(app, "ap-2"))
    show("1 laptop = $1,200 paused", ask(app, "ap-4", item="laptop", qty=1, weight=3, distance=120))
    show("human REJECTS", approve(app, "ap-4", "rejected"))
    print(f"    laptop stock after rejection: {STOCK['laptop']}")

    banner("U4-4 CHALLENGE: error propagation (inventory answer says 103, store has 3)")
    app = fresh()
    CACHE["mechanical_keyboard"] = 103                    # simulated stale cache: overwrite the agent's copy
    show("customer orders 10 keyboards ($1,200)", ask(app, "err", item="mechanical_keyboard", qty=10, weight=8, distance=40))
    print(f"    keyboard stock: {STOCK['mechanical_keyboard']} | no bidding, no approval request, no commit")
