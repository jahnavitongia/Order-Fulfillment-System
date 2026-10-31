"""Graph builder and lightweight fallback for LangGraph."""
from typing import Any
from .states import OrderState

try:
    from langgraph.graph import StateGraph, END  # type: ignore
    LANGGRAPH_AVAILABLE = True
except Exception:  # pragma: no cover - fallback
    LANGGRAPH_AVAILABLE = False
    END = "__end__"

    class StateGraph:
        def __init__(self, state_schema: Any):
            self.nodes, self.edges, self.cond_edges, self.entry = {}, {}, {}, None

        def add_node(self, name, fn):
            self.nodes[name] = fn

        def set_entry_point(self, name):
            self.entry = name

        def add_edge(self, src, dst):
            self.edges[src] = dst

        def add_conditional_edges(self, src, cond_fn, mapping):
            self.cond_edges[src] = (cond_fn, mapping)

        def compile(self):
            graph = self

            class Runner:
                def invoke(self, state):
                    node = graph.entry
                    while node != END:
                        state = graph.nodes[node](state)
                        if node in graph.cond_edges:
                            cond_fn, mapping = graph.cond_edges[node]
                            node = mapping[cond_fn(state)]
                        else:
                            node = graph.edges.get(node, END)
                    return state

            return Runner()


def build_graph():
    from . import nodes

    graph = StateGraph(OrderState)

    graph.add_node("check_inventory", nodes.check_inventory)
    graph.add_node("calculate_shipping", nodes.calculate_shipping)
    graph.add_node("confirm_order", nodes.confirm_order)
    graph.add_node("decline_order", nodes.decline_order)

    graph.set_entry_point("check_inventory")

    graph.add_conditional_edges(
        "check_inventory",
        nodes.route_after_inventory,
        {"proceed": "calculate_shipping", "decline": "decline_order"},
    )

    graph.add_edge("calculate_shipping", "confirm_order")
    graph.add_edge("confirm_order", END)
    graph.add_edge("decline_order", END)

    return graph.compile()
