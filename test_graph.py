"""Unit tests (no LLM, no network).  Run:  python -m unittest -v test_graph"""
import os
import unittest

os.environ["ORDER_USE_LLM"] = "0"   # deterministic: tests must not depend on Ollama

from order_fulfillment import process_order, run_order, resume_order, approve_order  # noqa: E402
from order_fulfillment import runner  # noqa: E402
from order_fulfillment.store import Store, use_store, get_store  # noqa: E402
from order_fulfillment.agents import ShippingAgent  # noqa: E402
from order_fulfillment.couriers import Courier, COURIERS  # noqa: E402
from order_fulfillment.rag import get_index, ask_policy  # noqa: E402
from order_fulfillment.config import APPROVAL_THRESHOLD  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        runner._APP = None
        self.store = use_store(Store.fresh())          # fresh seeded DB for every test

    def stock(self, item):
        return get_store().get_item(item)["stock"]


def order(item, qty, w=1.0, d=10):
    return process_order({"item": item, "requested_qty": qty, "weight_kg": w, "distance_km": d})


# ----------------------------------------------------------------- jury-1 behaviour
class TestFulfilledPath(Base):
    def test_path_cost_and_stock(self):
        r = order("wireless_mouse", 5, 1.2, 15)
        self.assertEqual(r["status"], "confirmed")
        self.assertEqual(r["path"], ["check_inventory", "calculate_shipping", "policy_lookup",
                                     "human_approval", "confirm_order"])
        self.assertEqual((r["courier"], r["shipping_cost"]), ("BudgetPost", 3.75))  # 2.5*1.2 + 0.05*15
        self.assertEqual(self.stock("wireless_mouse"), 37)                           # 42 - 5

    def test_exact_stock_is_sufficient(self):
        self.assertEqual(order("mechanical_keyboard", 3)["status"], "confirmed")
        self.assertEqual(self.stock("mechanical_keyboard"), 0)


class TestDeclinedPath(Base):
    def test_insufficient_never_touches_shipping(self):
        r = order("mechanical_keyboard", 10, 8.0, 40)
        self.assertEqual((r["status"], r["reason"], r["stock"]), ("declined", "insufficient_stock", 3))
        self.assertEqual(r["path"], ["check_inventory", "decline_order"])
        self.assertNotIn("shipping_cost", r)
        self.assertEqual(self.stock("mechanical_keyboard"), 3)
        self.assertEqual(get_store().list_shipments(), [])

    def test_other_decline_reasons(self):
        self.assertEqual(order("usb_c_hub", 1)["reason"], "out_of_stock")
        self.assertEqual(order("flux_capacitor", 1)["reason"], "unknown_item")
        for q in (0, -4):
            r = order("wireless_mouse", q)
            self.assertEqual(r["reason"], "invalid_quantity")
            self.assertNotIn("calculate_shipping", r["path"])

    def test_bad_payload_raises(self):
        with self.assertRaises(ValueError):
            process_order({"item": "x"})
        with self.assertRaises(ValueError):
            order("wireless_mouse", "abc")


class TestInvariant(Base):
    def test_shipping_and_confirm_only_after_inventory_ok(self):
        for item, q in [("wireless_mouse", 1), ("wireless_mouse", 43), ("mechanical_keyboard", 4),
                        ("usb_c_hub", 1), ("nope", 1), ("wireless_mouse", 0)]:
            r = order(item, q)
            ran = set(r["path"])
            if r["status"] == "confirmed":
                self.assertIn("calculate_shipping", ran)
            else:
                self.assertTrue(ran.isdisjoint({"calculate_shipping", "confirm_order"}))
            self.assertEqual(r["path"][0], "check_inventory")


# ----------------------------------------------------------------- Unit 3
class TestSQLite(Base):
    def test_data_survives_restart(self):
        r = order("wireless_mouse", 5, 1.2, 15)
        reopened = use_store(Store(self.store.path))               # new connection, same file
        self.assertEqual(reopened.get_item("wireless_mouse")["stock"], 37)
        row = reopened.get_order(r["thread_id"])
        self.assertEqual((row["status"], row["courier"]), ("confirmed", "BudgetPost"))
        self.assertEqual(len(reopened.list_shipments()), 1)

    def test_guarded_decrement_never_goes_negative(self):
        self.assertTrue(self.store.reserve_stock("mechanical_keyboard", 3))
        self.assertFalse(self.store.reserve_stock("mechanical_keyboard", 1))
        self.assertEqual(self.stock("mechanical_keyboard"), 0)


class TestCheckpointResume(Base):
    def test_crash_then_resume(self):
        r = run_order("laptop", 1, 3.0, 120, crash_after="calculate_shipping")
        tid = r["thread_id"]
        self.assertEqual(r["status"], "interrupted")
        self.assertEqual([c["node"] for c in self.store.list_checkpoints(tid)],
                         ["check_inventory", "calculate_shipping"])
        runner._APP = None                                         # "new process"
        r2 = resume_order(tid)
        self.assertEqual(r2["status"], "awaiting_approval")        # laptop is high-value
        self.assertEqual(sum(l.startswith("[check_inventory]") for l in r2["trace"]), 1)  # NOT re-run
        r3 = approve_order(tid, "approved", "manager")
        self.assertEqual(r3["status"], "confirmed")
        self.assertEqual(self.stock("laptop"), 4)                  # deducted exactly once

    def test_resume_of_finished_order_is_noop(self):
        r = run_order("wireless_mouse", 1, 1.0, 10)
        resume_order(r["thread_id"])
        self.assertEqual(self.stock("wireless_mouse"), 41)

    def test_commit_is_idempotent(self):
        from order_fulfillment.agents import OrderAgent
        r = run_order("wireless_mouse", 2, 1.0, 10)
        st = {**self.store.latest_checkpoint(r["thread_id"])["state"]}
        self.assertTrue(OrderAgent(self.store).commit(st))         # retry after "crash"
        self.assertEqual(self.stock("wireless_mouse"), 40)


class TestRAG(Base):
    def test_retrieval_finds_right_clause(self):
        idx = get_index()
        self.assertEqual(idx.retrieve("Which courier can carry a 40 kg parcel?", 1)[0]["id"], "1.2")
        self.assertEqual(idx.retrieve("When do I need approval for an expensive order?", 1)[0]["id"], "3.1")
        self.assertEqual(idx.retrieve("How long do I have to return an item?", 1)[0]["id"], "6.1")

    def test_answer_cites_a_retrieved_clause(self):
        a = ask_policy("How long do I have to return an item?")
        self.assertIn("6.1", a["sources"])
        self.assertIn("14 days", a["answer"])

    def test_policy_document_matches_config(self):
        text = open(os.path.join(os.path.dirname(runner.__file__), "shipping_policy.md")).read()
        self.assertIn(f"{APPROVAL_THRESHOLD:.2f}", text)
        for c in COURIERS:
            self.assertIn(c.name, text)
            self.assertIn(f"up to {c.max_kg:g} kg", text)
            self.assertIn(f"up to {c.max_km:g} km", text)

    def test_workflow_cites_policy(self):
        r = order("wireless_mouse", 1, 1.0, 10)
        self.assertTrue(r["policy_refs"])
        self.assertIn("Policy:", r["message"])


# ----------------------------------------------------------------- Unit 4
class TestAuction(Base):
    def test_cheapest_eligible_wins(self):
        bids, w = ShippingAgent().call_for_proposals(2.0, 10)
        self.assertEqual(w["courier"], "LocalBike")
        self.assertEqual(w["price"], min(b["price"] for b in bids if b["status"] == "BID"))

    def test_refusals_have_reasons(self):
        bids, w = ShippingAgent().call_for_proposals(40.0, 800)
        self.assertEqual(w["courier"], "SpeedyExpress")
        self.assertTrue(all(b["reason"] for b in bids if b["status"] == "REFUSED"))

    def test_tie_break_faster_then_name(self):
        a = Courier("Aaa", 0, 1, 0, 99, 99, 3)
        b = Courier("Bbb", 0, 1, 0, 99, 99, 1)
        c = Courier("Ccc", 0, 1, 0, 99, 99, 1)
        _, w = ShippingAgent([a, b, c]).call_for_proposals(10, 10)
        self.assertEqual(w["courier"], "Bbb")                      # same price; faster beats Aaa; name beats Ccc

    def test_no_eligible_courier_declines(self):
        r = order("monitor", 1, 80.0, 100)
        self.assertEqual((r["status"], r["reason"]), ("declined", "no_courier_available"))
        self.assertEqual(self.stock("monitor"), 10)


class TestApproval(Base):
    def test_below_threshold_auto_approved(self):
        r = order("wireless_mouse", 19, 3.0, 10)                   # $475
        self.assertEqual(r["status"], "confirmed")
        self.assertFalse(r["approval_required"])

    def test_boundary_is_inclusive(self):
        r = order("wireless_mouse", 20, 3.0, 10)                   # exactly $500
        self.assertEqual((r["status"], r["approval_required"]), ("awaiting_approval", True))
        self.assertEqual(self.stock("wireless_mouse"), 42)         # nothing deducted while waiting

    def test_approve_and_reject(self):
        r = order("laptop", 1, 3.0, 50)
        self.assertEqual(approve_order(r["thread_id"], "approved")["status"], "confirmed")
        self.assertEqual(self.stock("laptop"), 4)
        r = order("monitor", 2, 12.0, 30)                          # $600
        res = approve_order(r["thread_id"], "rejected")
        self.assertEqual((res["status"], res["reason"]), ("declined", "rejected_by_approver"))
        self.assertEqual(self.stock("monitor"), 10)

    def test_resume_without_decision_keeps_waiting(self):
        r = order("laptop", 1, 3.0, 50)
        st = resume_order(r["thread_id"])
        self.assertEqual(st["approval"], "pending")
        with self.assertRaises(ValueError):
            approve_order(r["thread_id"], "maybe")


class TestErrorPropagation(Base):
    def _run(self, verify, safe):
        r = run_order("mechanical_keyboard", 10, 8.0, 40, inventory_fault="overstate",
                      verify_inventory=verify, safe_commit=safe)
        if r["status"] == "awaiting_approval":
            r = resume_order(r["thread_id"], "approved", "manager")
        return r

    def test_A_no_fix_oversells(self):
        r = self._run(False, False)
        self.assertEqual(r["status"], "confirmed")
        self.assertEqual(self.stock("mechanical_keyboard"), -7)    # ledger corrupted
        self.assertEqual(len(get_store().list_shipments()), 1)

    def test_B_commit_guard_stops_corruption(self):
        r = self._run(False, True)
        self.assertEqual((r["status"], r["decline_reason"]), ("declined", "commit_failed"))
        self.assertEqual(self.stock("mechanical_keyboard"), 3)
        self.assertIn("calculate_shipping", r["path"])             # but downstream work was wasted

    def test_C_verification_catches_it_at_the_source(self):
        r = self._run(True, True)
        self.assertEqual((r["status"], r["decline_reason"]), ("declined", "insufficient_stock"))
        self.assertEqual(r["path"], ["check_inventory", "decline_order"])
        self.assertEqual(self.stock("mechanical_keyboard"), 3)
        self.assertTrue(any("DISCREPANCY" in l for l in r["trace"]))


# ----------------------------------------------------------------- memory / supervisor / eval
class TestStrictRAG(Base):
    def test_says_dont_know_when_policy_is_silent(self):
        for q in ["Does BudgetPost deliver on weekends?", "Do you ship to Mars?", "Can I pay with bitcoin?"]:
            self.assertIn("don't know", ask_policy(q)["answer"], q)

    def test_still_answers_covered_questions(self):
        for q in ["How long does EcoShip take to deliver?", "What happens if my parcel arrives damaged?"]:
            self.assertNotIn("don't know", ask_policy(q)["answer"], q)


class TestSupervisor(Base):
    def test_short_term_memory_fills_follow_up(self):
        from order_fulfillment.supervisor import Supervisor
        s = Supervisor("alice")
        s.handle("Order 5 wireless mouse, 1.2 kg, 15 km")
        s.handle("make it 3 instead")
        self.assertEqual((s.last_order["status"], s.last_order["requested_qty"]), ("confirmed", 3))
        self.assertEqual(self.stock("wireless_mouse"), 34)

    def test_long_term_memory_survives_restart(self):
        from order_fulfillment.supervisor import Supervisor
        Supervisor("alice").handle("Order 1 monitor, 4 kg, 60 km")   # $300: no approval needed
        runner._APP = None
        use_store(Store(self.store.path))                  # "restart": new objects, same SQLite file
        s = Supervisor("alice")
        self.assertEqual(s.short.slots, {})                # short-term is gone
        self.assertEqual(s.long.recall()["distance_km"], 60.0)
        s.handle("Order 1 monitor 4 kg")                   # distance comes from long-term memory
        self.assertEqual(s.last_order["status"], "confirmed")

    def test_routes_to_each_agent_and_stops_at_max_hops(self):
        from order_fulfillment.supervisor import Supervisor
        r = Supervisor("bob", max_hops=2).handle(
            "Do you have 2 laptops? What is the return policy? Order 1 laptop 3 kg 10 km")
        self.assertEqual([h["agent"] for h in r["hops"]], ["inventory", "policy"])
        self.assertTrue(r["stopped_by_max_hops"])
        self.assertEqual(self.stock("laptop"), 5)          # the 3rd task (order) never ran

    def test_approval_through_chat(self):
        from order_fulfillment.supervisor import Supervisor
        s = Supervisor("carol")
        s.handle("Order 1 laptop 3 kg 120 km")
        self.assertEqual(s.last_order["status"], "awaiting_approval")
        s.handle("approve it")
        self.assertEqual(s.last_order["status"], "confirmed")


class TestEvaluation(unittest.TestCase):
    def test_ta2_passes_all_ta1_only_simple_order(self):
        import evaluate
        ta1 = [evaluate.run_case(evaluate.TA1, c)["pass"] for c in evaluate.CASES]
        ta2 = [evaluate.run_case(evaluate.TA2, c)["pass"] for c in evaluate.CASES]
        self.assertEqual(ta1, [True, False, False, False, False])
        self.assertEqual(ta2, [True] * 5)


if __name__ == "__main__":
    unittest.main()
