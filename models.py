#models.py
from pydantic import BaseModel
from typing import List, Dict
from datetime import datetime

class Action(BaseModel):
    action_type: str  # e.g., "view", "add_to_cart", "purchase"
    item_id: str
    timestamp: datetime

class Session(BaseModel):
    user_id: str
    session_id: str
    actions: List[Action]
    created_at: datetime = datetime.utcnow()