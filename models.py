#models.py
from pydantic import BaseModel
from typing import List, Dict
from datetime import datetime


class Event(BaseModel):
    aid: int
    ts: int
    type: int

class Session(BaseModel):
    session_id: str
    events: List[Event]

