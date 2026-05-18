from app.graph.state import AssistantState




def route_intent(state: AssistantState):

    intent = state["intent"]

    if intent == "hotel_qa":

        return "rag_node"

    elif intent == "create_reservation":

        return "extract_reservation"

    elif intent in [
        "view_reservation",
        "cancel_reservation"
    ]:

        return "tool_node"
    
    elif intent == "general_interactions":

        return "general_node"

    else:

        return "reject_node"