"""Graph builder (LangGraph, with a tiny fallback engine when `langgraph` is missing),
SQLite checkpointing after every node, and resume support."""
from typing import Any
from .states import OrderState, note
from . import nodes
from .store import get_store

try:
    from langgraph.graph import StateGraph, END, START  # type: ignore
    LANGGRAPH_AVAILABLE = True
except Exception:  # pragma: no cover - fallback
    LANGGRAPH_AVAILABLE = False
    END, START = "__end__", "__start__"

    class StateGraph:  # minimal stand-in with the same API surface we use
        def __init__(self, state_schema: Any):
            self.nodes, self.edges, self.cond_edges = {}, {}, {}

        def add_node(self, name, fn):
            self.nodes[name] = fn

        def add_edge(self, src, dst):
            self.edges[src] = dst

        def add_conditional_edges(self, src, cond_fn, mapping):
            self.cond_edges[src] = (cond_fn, mapping)

        def compile(self):
            graph = self

            class Runner:
                def invoke(self, state):
                    cond_fn, mapping = graph.cond_edges[START]
                    node = mapping[cond_fn(state)]
                    while node != END:
                        state = graph.nodes[node](state)
                        if node in graph.cond_edges:
                            cond_fn, mapping = graph.cond_edges[node]
                            node = mapping[cond_fn(state)]
                        else:
                            node = graph.edges.get(node, END)
                    return state

            return Runner()


class SimulatedCrash(RuntimeError):
    """Raised on purpose (state['crash_after']) to demonstrate resume from a checkpoint."""


NODES = {
    "check_inventory": nodes.check_inventory,
    "calculate_shipping": nodes.calculate_shipping,
    "policy_lookup": nodes.policy_lookup,
    "human_approval": nodes.human_approval,
    "confirm_order": nodes.confirm_order,
    "decline_order": nodes.decline_order,
}

# Single source of truth for the edges: used BOTH to build the graph and to work out
# "which node comes next?" when resuming from a checkpoint.
CONDITIONAL = {
    "check_inventory":    (nodes.route_after_inventory, {"proceed": "calculate_shipping", "decline": "decline_order"}),
    "calculate_shipping": (nodes.route_after_shipping,  {"awarded": "policy_lookup", "none": "decline_order"}),
    "human_approval":     (nodes.route_after_approval,  {"approved": "confirm_order", "rejected": "decline_order", "pending": END}),
    "confirm_order":      (nodes.route_after_confirm,   {"committed": END, "failed": "decline_order"}),
}
LINEAR = {"policy_lookup": "human_approval", "decline_order": END}


def next_node(last_node: str, state: dict) -> str:
    if last_node in CONDITIONAL:
        fn, mapping = CONDITIONAL[last_node]
        return mapping[fn(state)]
    return LINEAR[last_node]


def _checkpointed(name, fn):
    """Run a node, then persist the full state to SQLite (the checkpoint)."""
    def run(state):
        state = fn(state)
        state["step"] = state.get("step", 0) + 1
        get_store().save_checkpoint(state["thread_id"], state["step"], name, dict(state))
        if state.get("crash_after") == name:
            raise SimulatedCrash(f"simulated crash after '{name}' (step {state['step']})")
        return state
    return run


def entry_router(state: OrderState) -> str:
    return state.get("resume_from") or "check_inventory"


MERMAID = """\
flowchart TD
    S([START]) -->|new order| A[check_inventory]
    S -.->|resume_from checkpoint| R(( any node ))
    A -- "proceed (inventory_ok)" --> B[calculate_shipping: courier auction]
    A -- "decline" --> D[decline_order]
    B -- "awarded" --> P[policy_lookup: RAG]
    B -- "no eligible courier" --> D
    P --> H[human_approval]
    H -- "approved / below threshold" --> C[confirm_order: atomic commit]
    H -- "rejected" --> D
    H -- "pending: PAUSE (checkpoint)" --> E([END])
    C -- "committed" --> E
    C -- "commit refused" --> D
    D --> E
"""


def build_graph():
    graph = StateGraph(OrderState)
    for name, fn in NODES.items():
        graph.add_node(name, _checkpointed(name, fn))

    # Entry: normally check_inventory; when resuming, jump to the node after the last checkpoint.
    graph.add_conditional_edges(START, entry_router, {n: n for n in NODES})

    for src, (fn, mapping) in CONDITIONAL.items():
        graph.add_conditional_edges(src, fn, mapping)
    for src, dst in LINEAR.items():
        graph.add_edge(src, dst)
    return graph.compile()
