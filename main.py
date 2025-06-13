# main.py
import os
import random
import joblib
import polars as pl
import logging
import time 

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
from contextlib import asynccontextmanager

from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import Gauge, Histogram


from process_pipeline import pipeline, apply
from kafka_producer import KafkaProducer
from models import Session ,Event      
from fastapi.middleware.cors import CORSMiddleware

import asyncio, socket

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# --- KHỞI TẠO CUSTOM METRICS CHO PROMETHEUS ---
# 1. Model Inference Latency: Theo dõi độ trễ của bước dự đoán
model_inference_latency = Histogram(
    'model_inference_latency_seconds',
    'Latency for a single model inference step (in seconds)'
)

# 2. Model Confidence Score: Theo dõi điểm tin cậy của model
model_confidence_score = Gauge(
    'model_confidence_score',
    'The average confidence score of the top K recommendations'
)

# 3. CPU Interface Time
model_cpu_inference_time_seconds = Histogram(
    'model_cpu_inference_time_seconds',
    'CPU time spent on a single model inference step (in seconds)'
)

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

# --- GẮN INSTRUMENTATOR VÀO APP ---
# Thao tác này sẽ tự động tạo các metrics API (RPS, latency, errors)
# và tạo ra endpoint /metrics
Instrumentator().instrument(app).expose(app)


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
    
    simulate_latency: Optional[bool] = False
    simulate_error: Optional[bool] = False

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

    # --- KHỐI CODE GIẢ LẬP KỊCH BẢN ---
    # Giả lập độ trễ cao (High Latency)
    if req.simulate_latency:
        
        latency_duration = random.uniform(1.5, 2.5)
        logger.info(f"Simulating high latency of {latency_duration:.2f}s for session {req.session_id}")
        await asyncio.sleep(latency_duration)

    # Giả lập lỗi (High Error Rate)
    if req.simulate_error:
        logger.warning(f"Simulating a 500 server error for session {req.session_id}")
        raise HTTPException(status_code=500, detail="Simulated Internal Server Error")
    # --- KẾT THÚC KHỐI GIẢ LẬP ---

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
    
    # --- BẮT ĐẦU ĐO LƯỜNG VÀ GHI NHẬN METRICS ---
    start_time = time.time()
    with model_inference_latency.time(): # Tự động đo latency cho khối code này
        start_cpu = time.process_time()
        if hasattr(ranker, "booster_"):
            scores = ranker.booster_.predict(X.values)
        else:
            scores = ranker.predict(X)
        cpu_duration = time.process_time() - start_cpu
        model_cpu_inference_time_seconds.observe(cpu_duration) # Ghi nhận CPU Time 
    # --- KẾT THÚC ĐO LƯỜNG ---

    # 3) Trả về top-k
    pairs = list(zip(df_cand["aid"].to_list(), scores))
    topk = sorted(pairs, key=lambda x: x[1], reverse=True)[: req.top_k]
    recs = [Recommendation(aid=aid, score=float(sc)) for aid, sc in topk]

    # --- GHI NHẬN CONFIDENCE SCORE ---
    if topk:
        # Lấy trung bình score của các sản phẩm được đề xuất làm confidence
        avg_confidence = sum(s for _, s in topk) / len(topk)
        model_confidence_score.set(avg_confidence)
        logger.info(f"Set model confidence score to: {avg_confidence:.4f}")

    logger.info(f"Successfully generated {len(recs)} recommendations for session {req.session_id}")

    return RecResponse(session_id=req.session_id, recommendations=recs)

