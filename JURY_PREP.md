# Jury prep - Order Fulfillment Graph (Jury 1 + Jury 2)

## Graph
```
START -> check_inventory --proceed--> calculate_shipping (courier auction) --awarded--> policy_lookup (RAG)
              |decline                     |no eligible courier                              |
              v                            v                                                 v
        decline_order <---------------- decline_order <--rejected-- human_approval --approved/auto--> confirm_order --committed--> END
                                                                         |pending: PAUSE (END, state saved)       |refused -> decline_order
```
Entry edge is conditional: normally `check_inventory`; when resuming, it jumps to the node after the last checkpoint.

## Jury 1 questions
**Why calculate shipping only after inventory is confirmed?** Shipping is the costly/side-effectful step (carrier calls); quoting a price for an order we can't ship is wasteful and misleading; fail fast with the cheapest check first. The graph enforces it: the only edge into `calculate_shipping` is the `proceed` branch (test: `TestInvariant`).

**How is decline_order triggered?** `check_inventory` computes `inventory_ok = item_known and available >= requested` and stores `route = proceed|decline`. `add_conditional_edges("check_inventory", route_after_inventory, {...})` calls the (read-only) router, which returns `state["route"]`; LangGraph looks it up in the mapping -> `decline_order`. The trace prints `(inventory_ok=False); ROUTE -> decline_order`.

## Jury 2 - Unit 3
**SQLite as persistent store.** Four tables: `inventory` (stock, unit_price), `orders` (every order incl. declined/interrupted, with reason), `shipments` (courier booking + tracking), `checkpoints`. Stock is deducted only at confirmation with ONE atomic statement: `UPDATE inventory SET stock = stock - ? WHERE item=? AND stock >= ?` - if no row changes, the commit is refused. This removes the Jury-1 limitation (static dict, race between check and commit). Proof: `jury2_demo.py` evidence 1 (restart, stock 42 -> 37 persists).

**Checkpointer / resume.** After every node the full state is saved to `checkpoints(thread_id, step, node, state_json)`. `resume_order(thread_id)` loads the latest checkpoint, computes the next node with the SAME edge table used to build the graph (`next_node`), sets `resume_from`, and the conditional START edge jumps there - earlier nodes are not re-run (trace shows `check_inventory` once). Commit is idempotent per `thread_id`, so a retry after a crash cannot deduct twice. Demo: crash after the auction, restart, resume, approve.
- *Honest note:* this is my own SQLite checkpointer, same idea as LangGraph's `SqliteSaver` + `interrupt()` (thread id, per-step snapshots, resume). I chose it so it works on both engines and I could test it; swapping to `SqliteSaver` would need `pip install langgraph-checkpoint-sqlite` and `interrupt()` in the approval node.

**RAG over shipping policy.** `shipping_policy.md` has 14 clauses with ids (1.1 ... 6.2). They are chunked per clause and indexed with BM25 (pure Python, stemming + small query expansion, e.g. "expensive" -> "high value"). `ask_policy()` retrieves top-k, asks the LLM to answer ONLY from those clauses and cite ids, and falls back to quoting the best clause if the reply cites none (grounding check). In the workflow, `policy_lookup` retrieves the clauses for the awarded courier / high-value rule and the confirmation cites them (`Policy: §1.1, §3.1`). A test checks the policy numbers match the code's config. *Why BM25 not embeddings:* no extra model download, deterministic, enough for 14 clauses; embeddings (nomic-embed-text) are the upgrade for a big corpus.

## Jury 2 - Unit 4
**Three agents.** `InventoryAgent` (answers stock questions), `ShippingAgent` (runs the auction), `OrderAgent` (order ledger + atomic commit). The LangGraph nodes are thin wrappers that call them.

**Contract-net bidding.** Shipping agent broadcasts a call for proposals (weight, distance). Each courier either BIDs (price, ETA) or REFUSEs with a reason (weight/distance limit). Cheapest eligible bid wins; tie -> faster delivery -> name. No eligible bid -> order declined (`no_courier_available`). Bid table is printed and returned by the API.

**How does the high-value rule work?** Goods value = quantity x unit price read from the database (shipping excluded; the user cannot supply the price). If value >= $500.00 (inclusive; threshold in `config.py`, documented in policy 3.1) the `human_approval` node sets status `awaiting_approval`, writes the order row, checkpoints, and the graph ends (paused). Nothing is deducted while waiting. `approve_order(thread_id, "approved"|"rejected")` resumes: approved -> `confirm_order`; rejected -> `decline_order` (`rejected_by_approver`). Below the threshold the node auto-approves and logs it. Demo shows $125 (auto), exactly $500 (pauses), $1200 laptop (approved), $600 (rejected).

**Where did a wrong inventory answer cause damage downstream?** (Demo: store has 3 keyboards, a stale-cache Inventory agent claims 103, customer orders 10 = $1200.)
- *No fix (A):* (1) the courier auction ran on a quantity that doesn't exist; (2) the approver was shown "stock on hand: 103" and approved on false information; (3) the ledger was corrupted - stock became -7 and a confirmed order + courier shipment exist for 7 units that never existed.
- *Commit guard only (B):* corruption stopped (commit refused, stock stays 3) but the auction and the manager's time were wasted.
- *Full fix (C):* `check_inventory` re-reads the authoritative store, logs `DISCREPANCY: claimed 103 but store has 3`, uses the store value, declines at step 1 - no auction, no approval request.
- Lesson: don't let one agent's unverified answer drive costly or irreversible actions; verify at the source AND guard at commit (defence in depth). The Inventory fault is simulated (`inventory_fault="overstate"`), not a real LLM hallucination.

## Other likely questions
- *Why isn't the LLM making decisions?* Stock, routing, approval and prices are deterministic and auditable; the LLM only phrases messages, and its output is checked for the real numbers (else a template is used, and the trace says so).
- *Limitations (be upfront):* no stock reservation while an order waits for approval (the commit guard handles the race by declining); courier prices are formulas, not real carrier APIs; one approver, no authentication; weight_kg is the total shipment weight; custom checkpointer rather than SqliteSaver.

## Memory, supervisor, strict RAG, evaluation
**Memory.** *Short-term* = `ShortTermMemory`: the last 10 turns + the order being discussed (item, qty, kg, km, order waiting for approval) for ONE conversation, in RAM. That is why "make it 3 instead" or "approve it" works. *Long-term* = `customer_memory` table in SQLite (last item, usual distance, orders placed), per customer, so after a restart "Order 1 monitor 4 kg" still knows the distance. Test: `TestSupervisor.test_long_term_memory_survives_restart` (short-term is empty after restart, long-term is not).

**Supervisor + max hops.** `Supervisor.handle(message)` splits the message into sentences, classifies each (order / approval / inventory / shipping / policy) and dispatches it to the matching agent; each dispatch is one hop. After `max_hops` (default 4) it stops and lists what it did not handle, so a runaway request or a future LLM router cannot loop forever. Routing is rules, not an LLM, so it is testable. Orders still go through the LangGraph workflow (which re-verifies stock, so defence in depth stays).

**"I don't know".** Retrieval alone always returns *something* that shares a word. So `ask_policy` also checks that every content word of the question appears in the retrieved clauses (prefix match: deliver ~ delivery; synonyms count). "Does BudgetPost deliver on weekends?" -> "weekend" is not covered -> "I don't know". If the LLM itself says it does not know, that is passed through. *Limitation:* it is lexical, so an unusual paraphrase can be refused; embeddings would fix that.

**Evaluation (TA1 vs TA2).** TA1 = Jury-1 baseline (fixed pipeline, one complete order per message, no memory, no policy agent, trusts the inventory answer, unguarded stock update). TA2 = Jury-2 system. Same 5 messages, same parser, fresh DB per case:
simple order / follow-up needing memory / policy question / question the policy does not answer / wrong inventory answer.
Result: TA1 1/5 (20%), leaves negative stock once; TA2 5/5 (100%), never. Cost: TA2 is ~1.5x slower per case and runs a few more nodes (it handled more requests). In case 5 TA2 runs fewer nodes (2 vs 5) because it stops the bad order at step 1.
