from pydantic import BaseModel
from typing import Optional


class ChatRequest(BaseModel):
    chatbot_id: str
    message: str
    session_id: Optional[str] = None


class ChatHistoryRequest(BaseModel):
    chatbot_id: str
    session_id: Optional[str] = None


class NewChatSessionRequest(BaseModel):
    chatbot_id: str

class DeleteSessionRequest(BaseModel):
    chatbot_id: str
    session_id: str