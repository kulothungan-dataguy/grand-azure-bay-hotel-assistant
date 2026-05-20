from langgraph.graph import StateGraph, END
from app.graph.state import AssistantState
from app.graph.nodes import (
    intent_router_node,
    rag_node,
    tool_node,
    reject_node,
    general_node,
    extract_reservation_node
)
from app.graph.router import route_intent


# NOTE: This graph is only invoked by the non-streaming /chat endpoint (used in
# tests and direct API calls). The streaming /chat/stream endpoint — the path
# real frontend users take — bypasses the graph for hotel_qa and
# general_interactions (using shared helpers from nodes.py instead) and only
# calls graph.invoke() for reservation and unsafe intents.
#
# Nodes exercised by /chat/stream:  tool_node, extract_reservation, reject_node
# Nodes exercised only by /chat:    intent_router, rag_node, general_node

builder = StateGraph(AssistantState)

builder.add_node("intent_router", intent_router_node)
builder.add_node("rag_node", rag_node)
builder.add_node("tool_node", tool_node)
builder.add_node("general_node", general_node)
builder.add_node("reject_node", reject_node)
builder.add_node("extract_reservation", extract_reservation_node)

builder.set_entry_point("intent_router")

builder.add_conditional_edges("intent_router", route_intent)

builder.add_edge("extract_reservation", "tool_node")
builder.add_edge("general_node", END)
builder.add_edge("rag_node", END)
builder.add_edge("tool_node", END)
builder.add_edge("reject_node", END)

graph = builder.compile()
