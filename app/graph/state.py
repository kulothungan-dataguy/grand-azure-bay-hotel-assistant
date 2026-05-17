from typing import TypedDict, Optional

class AssistantState(TypedDict):
    query: str
    intent: Optional[str]
    retrieved_context: Optional[str]
    response: Optional[str]
    reservation_data: Optional[dict]
    chat_history: Optional[list]
    current_reservation: Optional[dict]
    reservation_id: Optional[int]