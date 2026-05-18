from typing import TypedDict, Optional

class AssistantState(TypedDict):
    query: str
    intent: Optional[str]
    response: Optional[str]
    reservation_data: Optional[dict]
    chat_history: Optional[list]
    current_reservation: Optional[dict]
    reservation_id: Optional[int]
    reservation_list: Optional[list]
    pending_cancel: Optional[dict]  # {"reservation_id": int, "email": str}