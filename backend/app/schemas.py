from pydantic import BaseModel
from typing import List, Optional, Dict, Any

class ChatResponse(BaseModel):
    id: str
    title: str
    created_at: str

class FileResponse(BaseModel):
    id: str
    chat_id: str
    filename: str
    file_path: str
    file_type: str
    file_size: int
    status: str
    uploaded_at: str

class ChatMessageRequest(BaseModel):
    query: str
    provider: Optional[str] = "ollama"
    top_k: int = 5

class ChatMessageResponse(BaseModel):
    id: str
    chat_id: str
    role: str
    content: str
    sources: Optional[List[Dict[str, Any]]] = None
    created_at: str
