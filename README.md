# TA2 submission (Jury 2): `ta1/` + `ta2/` + `traces/`
| Folder | What |
|---|---|
| `ta1/` | Frozen TA1 (Jury 1) code, unchanged: 4 nodes, stock in a dict, no stock deduction, no qty check |
| `ta2/order_ta2.py` | **TA2 prototype, 120 lines**: supervisor (MAX_HOPS=8, `hop_limit`) + inventory, guard, shipping, order, policy agents; thread memory (`SqliteSaver` + thread_id), long-term memory (`SqliteStore`), RAG (Chroma + nomic-embed-text), human approval (`interrupt()`), courier-quote timeout retried once |
| `ta2/demo.py` | Runs every module and prints the traces |
| `ta2/evaluate.py` | Same 5 test cases on TA1 and TA2: 3 checks each + LLM calls, graph steps, seconds |
| `traces/` | Saved outputs: `ta1_traces.txt`, `ta2_traces.txt`, `evaluation.txt` |

```
pip install -r requirements.txt
ollama pull qwen2.5:3b
ollama pull nomic-embed-text                  # Ollama must be running
python ta2/demo.py > traces/ta2_traces.txt
python ta2/evaluate.py > traces/evaluation.txt
cd ta1 && python "order_fulfillment_graph (1).py" > ../traces/ta1_traces.txt
```
Result: TA1 passes 2/15 checks, TA2 15/15. TA2 costs 3.5x graph steps and ~1.5x time.

### Dashboard (runs on TA2)
```
python ta2/server.py                          # terminal 1, API on http://localhost:8000
cd frontend && npm install && npm run dev     # terminal 2, open http://localhost:5173
```
New order form, approval queue, stock levels, courier bids per order, customer memory (reorder, change quantity on
the same thread), policy desk with quoted clauses, recent orders. The agent trace is under "How this was decided".
`ta2/server.py` keeps memory in `ta2/ui_threads.db` + `ta2/ui_store.db`; "Restock and clear" resets stock and lists only.

Everything below this line describes the earlier, larger Jury-2 extension (`order_fulfillment/`, `server.py`, UI). It is not part of the 120-line TA2 prototype.

---

# Topic 8 - Order Fulfillment Workflow Graph
LangGraph + Ollama (qwen2.5:3b) + SQLite + RAG + multi-agent courier bidding

## Run (Mac / Linux)
```
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
ollama pull qwen2.5:3b                       # Ollama must be running (brew services start ollama)

python -m unittest -v test_graph             # 26 tests, no LLM needed (also verifies the real LangGraph engine)
python "order_fulfillment_graph (1).py" > annotated_traces_output.txt   # Jury 1 traces (cases A-D)
python jury2_demo.py > jury2_evidence.txt                              # Jury 2 evidence (Unit 3 + Unit 4)
python evaluate.py > evaluation_results.txt                            # same 5 cases on TA1 vs TA2
```
First line of both outputs must say `REAL langgraph package`, and messages should say
`written by: LLM qwen2.5:3b`.

## UI
```
python server.py                             # terminal 1, http://localhost:8000
cd frontend && npm install && npm run dev    # terminal 2
```
Header badge shows `live: ...` when connected. Use "Reset demo data" to restore stock (the database persists
in `order_fulfillment.db`, so orders really deduct stock).

## What maps to the syllabus
| Requirement | Where |
|---|---|
| SQLite inventory + order store | `order_fulfillment/store.py` (tables: inventory, orders, shipments, checkpoints) |
| Checkpointer, resume interrupted order | `graph_wrapper._checkpointed`, `runner.resume_order` |
| RAG over shipping policy | `order_fulfillment/shipping_policy.md`, `rag.py`, node `policy_lookup` |
| Inventory / Shipping / Order agents | `order_fulfillment/agents.py` |
| Couriers bid, cheapest eligible wins | `couriers.py`, `ShippingAgent.call_for_proposals` |
| Human approval for high-value orders | node `human_approval` (threshold in `config.py`) |
| Error propagation + fix | `jury2_demo.py` section "UNIT 4 / EVIDENCE 3" |
| Short-term memory (one conversation) | `memory.ShortTermMemory` (RAM: recent turns + order slots, e.g. "make it 3 instead") |
| Long-term memory (survives restart) | `memory.LongTermMemory`, SQLite table `customer_memory` |
| RAG says "I don't know" | `rag.missing_terms`: every content word must be covered by a retrieved clause |
| Policy agent + supervisor, max hops | `agents.PolicyAgent`, `supervisor.Supervisor(max_hops=4)`, `POST /chat` |
| Evaluation TA1 vs TA2 | `evaluate.py` (TA1 = Jury-1 baseline, TA2 = Jury-2 system) -> `evaluation_results.txt` |

## Layout
- `order_fulfillment/nodes.py` nodes + routing functions - `graph_wrapper.py` graph, edges, checkpointing
- `order_fulfillment/runner.py` run/resume/approve + trace printing - `server.py` HTTP API for the UI
- `test_graph.py` tests - `jury2_demo.py` evidence script - `JURY_PREP.md` answers to likely questions
