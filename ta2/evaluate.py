"""Same 5 test cases on frozen TA1 (ta1/) and TA2 (ta2/), compared with numbers. Ollama must be running.

    python ta2/evaluate.py > traces/evaluation.txt

Each case has 3 pass/fail checks. We also record LLM calls, graph steps and seconds per case.
The cases follow the five TA1 limits on slide 2; case 2 checks TA2 does not regress on a basic order.
"""
import os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "ta1"))                      # frozen TA1 package
from order_fulfillment import nodes as ta1_nodes                         # noqa: E402
from order_fulfillment.config import INVENTORY_DB                        # noqa: E402
from order_fulfillment.graph_wrapper import build_graph                  # noqa: E402
from demo import fresh, ask, approve, STOCK, CACHE                       # noqa: E402  (TA2)

TA1_SEED, TA1_LLM = dict(INVENTORY_DB), [0]
_real_llm = ta1_nodes.call_local_llm
def _counted_llm(prompt):
    TA1_LLM[0] += 1
    return _real_llm(prompt)
ta1_nodes.call_local_llm = _counted_llm                                   # count TA1 LLM calls without changing TA1

CASES = {1: "Wrong inventory answer: claims 103, has 3",
         2: "Basic order: 5 mice, 1.2 kg, 15 km",
         3: "High-value order: 40 mice = $1,000",
         4: "Follow-up 'make it 3' on the same thread",
         5: "Policy question + refusal + qty 0"}
CHECKS = {1: ["declined", "no shipping on bad data", "no oversell"],
          2: ["confirmed", "shipping $3.75", "stock 42->37"],
          3: ["paused for a human", "nothing deducted while waiting", "approved -> confirmed, stock 2"],
          4: ["follow-up confirmed", "item recalled from thread", "stock 42->34"],
          5: ["answers 14 days citing [6.1]", "says I don't know", "qty 0 refused"]}


# ------------------------------------------------------------------ TA1: returns (checks, steps)
def ta1_order(item=None, qty=None, weight=None, distance=None):
    """TA1 has no memory: every call must carry the full order."""
    return build_graph().invoke({"item": item, "requested_qty": qty, "weight_kg": weight, "distance_km": distance, "trace": []})
def ok1(r): return "shipping_cost" in r                                  # TA1 confirmed the order


def ta1_case(n):
    if n == 1:
        INVENTORY_DB["mechanical_keyboard"] = 103                         # the same wrong inventory answer
        r = ta1_order("mechanical_keyboard", 10, 8, 40)
        return [not ok1(r), "calculate_shipping" not in str(r["trace"]), not ok1(r)], len(r["trace"])
    if n == 2:
        r = ta1_order("wireless_mouse", 5, 1.2, 15)
        return [ok1(r), r.get("shipping_cost") == 3.75, INVENTORY_DB["wireless_mouse"] == 37], len(r["trace"])
    if n == 3:
        r = ta1_order("wireless_mouse", 40, 3, 30)                        # TA1 has no approval step: confirms at once
        return [not ok1(r), False, INVENTORY_DB["wireless_mouse"] == 2], len(r["trace"])
    if n == 4:
        r1 = ta1_order("wireless_mouse", 5, 1.2, 15)
        try:
            r2 = ta1_order(qty=3)                                         # follow-up with only the new quantity
        except Exception as e:
            print(f"    TA1 case 4 follow-up crashed: {type(e).__name__}: {e}")
            return [False, False, False], len(r1["trace"])
        return [ok1(r2), r2.get("item") == "wireless_mouse", INVENTORY_DB["wireless_mouse"] == 34], len(r1["trace"]) + len(r2["trace"])
    r = ta1_order("wireless_mouse", 0, 1, 10)                             # TA1 has no policy agent and no qty check
    return [False, False, not ok1(r)], len(r["trace"])


# ------------------------------------------------------------------ TA2: returns (checks, steps, llm calls)
def ta2_case(n):
    app, calls = fresh(), (lambda *rs: sum(r.get("llm_calls", 0) for r in rs))
    if n == 1:
        CACHE["mechanical_keyboard"] = 103
        r = ask(app, "c1", item="mechanical_keyboard", qty=10, weight=8, distance=40)
        return [r["status"] == "declined", "shipping_agent" not in str(r["trace"]), STOCK["mechanical_keyboard"] == 3], len(r["trace"]), calls(r)
    if n == 2:
        r = ask(app, "c2", item="wireless_mouse", qty=5, weight=1.2, distance=15)
        return [r["status"] == "confirmed", r.get("price") == 3.75, STOCK["wireless_mouse"] == 37], len(r["trace"]), calls(r)
    if n == 3:
        r = ask(app, "c3", item="wireless_mouse", qty=40, weight=3, distance=30)
        paused, waiting = "__interrupt__" in r, STOCK["wireless_mouse"]
        r = approve(app, "c3")
        return [paused, waiting == 42, r["status"] == "confirmed" and STOCK["wireless_mouse"] == 2], len(r["trace"]), calls(r)
    if n == 4:
        r1 = ask(app, "c4", item="wireless_mouse", qty=5, weight=1.2, distance=15)
        r2 = ask(app, "c4", qty=3)
        return ([r2["status"] == "confirmed", r2.get("item") == "wireless_mouse", STOCK["wireless_mouse"] == 34],
                len(r1["trace"]) + len(r2["trace"]), calls(r1, r2))
    a = ask(app, "c5a", request="question", question="How long do I have to return an item?")
    b = ask(app, "c5b", request="question", question="Do you offer gift wrapping?")
    c = ask(app, "c5c", item="wireless_mouse", qty=0, weight=1, distance=10)
    print(f"    TA2 case 5 answers: {a['message']!r} | {b['message']!r}")
    return ([("14" in a["message"]) and "[6.1]" in a["message"], "don't know" in b["message"].lower(), c["status"] == "declined"],
            len(a["trace"]) + len(b["trace"]) + len(c["trace"]), calls(a, b, c))


def run(name, n):
    INVENTORY_DB.clear(); INVENTORY_DB.update(TA1_SEED); before = TA1_LLM[0]
    t0 = time.perf_counter()
    if name == "TA1":
        checks, steps = ta1_case(n); llm = TA1_LLM[0] - before
    else:
        checks, steps, llm = ta2_case(n)
    return {"checks": checks, "steps": steps, "llm": llm, "sec": time.perf_counter() - t0}


if __name__ == "__main__":
    print("Running each case on TA1 then TA2 (live Ollama: qwen2.5:3b, nomic-embed-text)")
    res = {name: {n: run(name, n) for n in CASES} for name in ("TA1", "TA2")}

    print("\n" + "=" * 104 + "\n PER-CHECK RESULTS\n" + "=" * 104)
    for n, title in CASES.items():
        print(f"\n Case {n}: {title}")
        for i, label in enumerate(CHECKS[n]):
            a, b = res["TA1"][n]["checks"][i], res["TA2"][n]["checks"][i]
            print(f"    {label:<36} TA1 {'PASS' if a else 'FAIL':<6} TA2 {'PASS' if b else 'FAIL'}")

    print("\n" + "=" * 104 + "\n COMPARISON TABLE (copy to slide 13)\n" + "=" * 104)
    print(f" {'Case':<46}{'Checks TA1':>11}{'TA2':>6}{'LLM TA1':>9}{'TA2':>5}{'Steps TA1':>11}{'TA2':>5}{'Sec TA1':>9}{'TA2':>7}")
    for n, title in CASES.items():
        a, b = res["TA1"][n], res["TA2"][n]
        print(f" {n}. {title:<43}{sum(a['checks']):>9}/3{sum(b['checks']):>4}/3{a['llm']:>9}{b['llm']:>5}"
              f"{a['steps']:>11}{b['steps']:>5}{a['sec']:>9.1f}{b['sec']:>7.1f}")
    tot = {k: {m: sum(r[m] if m != "checks" else sum(r["checks"]) for r in v.values()) for m in ("checks", "llm", "steps", "sec")}
           for k, v in res.items()}
    a, b = tot["TA1"], tot["TA2"]
    print(f" {'TOTAL':<46}{a['checks']:>8}/15{b['checks']:>3}/15{a['llm']:>9}{b['llm']:>5}{a['steps']:>11}{b['steps']:>5}"
          f"{a['sec']:>9.1f}{b['sec']:>7.1f}")
    print(f"\n Checks passed: TA1 {a['checks']}/15 ({100 * a['checks'] / 15:.0f}%), TA2 {b['checks']}/15 ({100 * b['checks'] / 15:.0f}%)")
    print(f" Cost of TA2: {b['steps'] / max(a['steps'], 1):.1f}x graph steps, {b['sec'] / max(a['sec'], 0.01):.1f}x time, "
          f"{b['llm']} vs {a['llm']} LLM calls (plus embedding calls for RAG)")
