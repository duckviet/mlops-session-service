#main.py
from fastapi import FastAPI, HTTPException
from models import Session, Action
from redis_client import RedisClient
from kafka_producer import KafkaProducer
import uuid

app = FastAPI()
redis_client = RedisClient()
# kafka_producer = KafkaProducer()

@app.post("/sessions/")
async def create_session(session: Session):
    session.session_id = str(uuid.uuid4())
    redis_client.save_session(session)
    # kafka_producer.send_session(session)
    return {"session_id": session.session_id}

@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    session = redis_client.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session

@app.post("/sessions/{session_id}/actions")
async def add_action(session_id: str, action: Action):
    print(session_id, action)
    session = redis_client.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    session.actions.append(action)
    redis_client.save_session(session)
    # kafka_producer.send_session(session)
    return {"message": "Action added"}