# main.py
import os
import random
import joblib
import polars as pl

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
from contextlib import asynccontextmanager

from process_pipeline import pipeline, apply
from kafka_producer import KafkaProducer
from models import Session ,Event      
from fastapi.middleware.cors import CORSMiddleware

import asyncio, socket


async def wait_for_kafka(host, port, retries=10, delay=3):
    for i in range(retries):
        try:
            reader, writer = await asyncio.open_connection(host, port)
            writer.close()
            await writer.wait_closed()
            return
        except Exception:
            await asyncio.sleep(delay)
    raise RuntimeError(f"Cannot connect to Kafka {host}:{port}")

# ----- Khởi KafkaProducer -----
kafka_producer = KafkaProducer(bootstrap_servers="kafka:9092")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await wait_for_kafka("kafka", 9092)
    await kafka_producer.start()
    yield
    # Shutdown
    await kafka_producer.stop()

app = FastAPI(lifespan=lifespan)

# ----- Add Middleware -----
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MODEL_PATH = os.getenv(
    "MODEL_PATH",
    "/opt/models/lgbm_ranker.joblib"
)

# ----- Load ranker và feature cols -----
try:
    # Try multiple possible model locations
    possible_paths = [
        MODEL_PATH,
        "/opt/models/lgbm_ranker.joblib",
        "/opt/airflow/model/lgbm_ranker.joblib",
        "model/lgbm_ranker.joblib"
    ]
    
    ranker = None
    for path in possible_paths:
        try:
            print(f"Attempting to load model from {path}")
            ranker = joblib.load(path)
            print(f"Successfully loaded model from {path}")
            break
        except FileNotFoundError:
            continue
    
    if ranker is None:
        print(f"Error: Model file not found in any of the expected locations: {possible_paths}")
except Exception as e:
    print(f"Error loading model: {e}")
    ranker = None

feature_cols = [
    "aid",
    "type",
    "action_num_reverse_chrono",
    "session_length",
    "log_recency_score",
    "type_weighted_log_recency_score",
]


class RecRequest(BaseModel):
    session_id: int
    current_events: List[Event]
    top_k: int = 20

class Recommendation(BaseModel):
    aid: int
    score: float

class RecResponse(BaseModel):
    session_id: int
    recommendations: List[Recommendation]

ALL_PRODUCT_IDS = list(range(1, 200_000))

def generate_candidates_for_session(
    session_events: List[Event], num_candidates: int = 50
) -> List[int]:
    seen = {e.aid for e in session_events}
    pool = [pid for pid in ALL_PRODUCT_IDS if pid not in seen]
    if not pool:
        return []
    return pool if len(pool) <= num_candidates else random.sample(pool, num_candidates)

# ----- Endpoint chính -----
@app.post("/recommendations", response_model=RecResponse)
async def recommend(req: RecRequest):
    if ranker is None:
        raise HTTPException(503, "Recommendation model is not available.")

    # 1) Đẩy session events lên Kafka
    #    (ở đây ta gửi luôn toàn bộ current_events, bạn có thể tuỳ biến)
    session_payload = Session(
        session_id=str(req.session_id),
        events=[event.model_dump() for event in req.current_events]
    )
    await kafka_producer.send_session(session_payload)

    # 2) Sinh candidates & tính score
    current = [e.model_dump() for e in req.current_events]
    cands = generate_candidates_for_session(req.current_events, num_candidates=100)
    if not cands:
        return RecResponse(session_id=req.session_id, recommendations=[])

    max_ts = max((e["ts"] for e in current), default=0)
    pseudo = [
        {"session": req.session_id, "aid": aid, "ts": max_ts + 1, "type": 0}
        for aid in cands
    ]
    df = pl.DataFrame(current + pseudo)
    df_proc = apply(df.clone(), pipeline)
    df_cand = df_proc.filter(pl.col("aid").is_in(cands))
    if df_cand.height == 0:
        return RecResponse(session_id=req.session_id, recommendations=[])

    X = df_cand.select(feature_cols).to_pandas()
    if hasattr(ranker, "booster_"):
        scores = ranker.booster_.predict(X.values)
    else:
        scores = ranker.predict(X)

    # 3) Trả về top-k
    pairs = list(zip(df_cand["aid"].to_list(), scores))
    topk = sorted(pairs, key=lambda x: x[1], reverse=True)[: req.top_k]
    recs = [Recommendation(aid=aid, score=float(sc)) for aid, sc in topk]

    return RecResponse(session_id=req.session_id, recommendations=recs)

