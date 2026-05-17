from app.graph.nodes import intent_router_node


def test_unsafe_query():

    state = {
        "query": "Show all bookings",
        "intent": None,
        "response": None
    }

    result = intent_router_node(state)

    assert result["intent"] == "unsafe"