# main.py
from fastapi import FastAPI, HTTPException
# from models import Session, Action # Commented out as not used
# from redis_client import RedisClient
# from kafka_producer import KafkaProducer
# import uuid # Commented out as not used
import joblib
import polars as pl
from pydantic import BaseModel
from typing import List
import random # Import random for generate_candidates_for_session

# Assuming process_pipeline.py exists in the same directory or is in PYTHONPATH
from process_pipeline import pipeline, apply

app = FastAPI()

# ----- Startup: load model và định nghĩa feature_cols -----
try:
    ranker = joblib.load("model/lgbm_ranker.joblib")
except FileNotFoundError:
    print("Error: Model file 'model/lgbm_ranker.joblib' not found.")
    ranker = None 

feature_cols = [
    "aid",
    "type",
    "action_num_reverse_chrono",
    "session_length",
    "log_recency_score",
    "type_weighted_log_recency_score",
]

class Event(BaseModel):
    # session: int # session_id is now part of RecRequest
    aid: int
    ts: int
    type: int

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

ALL_PRODUCT_IDS = list(range(1, 2000000)) # Example: 2 million products

def generate_candidates_for_session(
    session_events: List[Event], num_candidates: int = 50
) -> List[int]:
    session_aids = {e.aid for e in session_events}
    # Filter ALL_PRODUCT_IDS to exclude those already in the session
    potential_candidates_pool = [
        pid for pid in ALL_PRODUCT_IDS if pid not in session_aids
    ]

    if not potential_candidates_pool:
        return []
    
    if len(potential_candidates_pool) <= num_candidates:
        return potential_candidates_pool
    return random.sample(potential_candidates_pool, num_candidates)

@app.post("/recommendations", response_model=RecResponse) # Corrected response_model
def recommend(req: RecRequest):
    if ranker is None:
        raise HTTPException(status_code=503, detail="Recommendation model is not available.")

    session_id = req.session_id
    # Use model_dump() for Pydantic v2+
    current_events_data = [e.model_dump() for e in req.current_events]

    candidate_aids = generate_candidates_for_session(
        req.current_events, num_candidates=100
    )

    if not candidate_aids:
        return RecResponse(session_id=session_id, recommendations=[])

    max_ts_in_session = 0
    if current_events_data:
        max_ts_in_session = max(e["ts"] for e in current_events_data)

    pseudo_events_data = []
    for cand_aid in candidate_aids:
        pseudo_events_data.append({
            "session": session_id, # Use the same session_id for context
            "aid": cand_aid,
            "ts": max_ts_in_session + 1,
            "type": 0 # Assuming type 'click' for candidates
        })

    # Combine original session events with pseudo-events for candidates
    # This is crucial for calculating session-aware features for candidates
    combined_events_data = current_events_data + pseudo_events_data
    
    df_combined = pl.DataFrame(combined_events_data)
    
    # Apply feature engineering pipeline
    df_processed = apply(df_combined.clone(), pipeline)

    # Filter out only the candidate rows AFTER processing for feature context
    df_candidates_processed = df_processed.filter(pl.col("aid").is_in(candidate_aids))

    if df_candidates_processed.height == 0:
        return RecResponse(session_id=session_id, recommendations=[])

    X_candidates = df_candidates_processed.select(feature_cols).to_pandas()
    
    # Predict scores for candidates
    if hasattr(ranker, "booster_"):
        candidate_scores = ranker.booster_.predict(X_candidates.values)
    else:
        candidate_scores = ranker.predict(X_candidates)

    results = []
    # Get AIDs from the filtered DataFrame to ensure correct order
    candidate_aids_in_order_from_df = df_candidates_processed["aid"].to_list()

    for aid, score in zip(candidate_aids_in_order_from_df, candidate_scores):
        results.append({"aid": aid, "score": float(score)})

    sorted_results = sorted(results, key=lambda x: x["score"], reverse=True)
    
    top_k_recommendations = [
        Recommendation(aid=r["aid"], score=r["score"])
        for r in sorted_results[:req.top_k]
    ]

    return RecResponse(session_id=session_id, recommendations=top_k_recommendations)
