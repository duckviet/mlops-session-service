#redis_client.py
import redis
import json
from models import Session

class RedisClient:
    def __init__(self, host="redis", port=6380, db=0):
        self.client = redis.Redis(host=host, port=port, db=db, decode_responses=True)

    def save_session(self, session: Session):
        key = f"session:{session.session_id}"
        self.client.setex(key, 3600, session.model_dump_json())  # Expire after 1 hour

    def get_session(self, session_id: str) -> Session:
        key = f"session:{session_id}"
        data = self.client.get(key)
        if data:
            return Session(**json.loads(data))
        return None
