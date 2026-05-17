from pydantic import BaseModel
from typing import Optional


class ChatRequest(BaseModel):

    conversation_id: str
    query: str


class ChatResponse(BaseModel):

    response: str

    intent: str

    reservation_id: Optional[int] = None