from app.graph.nodes import intent_router_node


def test_booking_intent():

    state = {
        "query": "Book a room tomorrow",
        "intent": None,
        "response": None
    }

    result = intent_router_node(state)

    assert result["intent"] == "create_reservation"