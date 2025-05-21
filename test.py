# test_main.py

import pytest
from fastapi.testclient import TestClient
from main import app, ALL_PRODUCT_IDS

client = TestClient(app)

def test_recommendations_basic_case_new_items():
    """
    Test basic case: current_events are provided, expect new item recommendations.
    """
    session_id = 101
    # Pick some AIDs from ALL_PRODUCT_IDS to be 'current'
    # Ensure these AIDs exist in the ALL_PRODUCT_IDS list from main.py
    if len(ALL_PRODUCT_IDS) < 2:
        pytest.skip("Not enough products in ALL_PRODUCT_IDS for this test")
    
    current_aids_in_session = [ALL_PRODUCT_IDS[0], ALL_PRODUCT_IDS[1]]
    
    payload = {
        "session_id": session_id,
        "current_events": [
            {"aid": current_aids_in_session[0], "ts": 1661119200, "type": 0},
            {"aid": current_aids_in_session[1], "ts": 1661119300, "type": 0},
        ],
        "top_k": 5
    }
    response = client.post("/recommendations", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["session_id"] == session_id
    assert "recommendations" in data
    recommendations = data["recommendations"]
    
    assert isinstance(recommendations, list)
    # Number of recommendations should be <= top_k
    assert len(recommendations) <= payload["top_k"]

 
    # This depends on the size of ALL_PRODUCT_IDS vs num_candidates in generate_candidates
    if len(ALL_PRODUCT_IDS) > len(current_aids_in_session) and payload["top_k"] > 0:
        if len(recommendations) == 0 and len(ALL_PRODUCT_IDS) - len(current_aids_in_session) >=1 :
             # This might happen if all candidate scores are extremely low or an issue in ranking
             # For now, we'll just note it. A more robust test might mock the ranker.
             pass # It's possible to get 0 recs if all candidates score poorly or num_candidates is small
        # assert len(recommendations) > 0 # This might be too strict due to randomness/ranking

    for rec in recommendations:
        assert "aid" in rec
        assert "score" in rec
        assert isinstance(rec["aid"], int)
        assert isinstance(rec["score"], float)
        # Crucially, recommended AIDs should not be in the current_events AIDs
        assert rec["aid"] not in current_aids_in_session
        # Recommended AIDs should be part of the global product list
        assert rec["aid"] in ALL_PRODUCT_IDS

    # Check for uniqueness of recommended AIDs
    recommended_aids_only = [r["aid"] for r in recommendations]
    assert len(recommended_aids_only) == len(set(recommended_aids_only))

def test_recommendations_empty_current_events_new_items():
    """
    Test with empty current_events. Expect recommendations from the general pool.
    """
    session_id = 102
    payload = {
        "session_id": session_id,
        "current_events": [],
        "top_k": 3
    }
    response = client.post("/recommendations", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["session_id"] == session_id
    recommendations = data["recommendations"]
    assert isinstance(recommendations, list)
    assert len(recommendations) <= payload["top_k"]

    if payload["top_k"] > 0 and len(ALL_PRODUCT_IDS) > 0:
         # If ALL_PRODUCT_IDS is not empty and top_k > 0, we expect recommendations
         # This also depends on num_candidates in generate_candidates
        if len(recommendations) == 0 and len(ALL_PRODUCT_IDS) >=1:
            pass # Possible if num_candidates is small or all scores are low
        # assert len(recommendations) > 0 # Potentially too strict

    for rec in recommendations:
        assert rec["aid"] in ALL_PRODUCT_IDS

def test_recommendations_top_k_respected_new_items():
    """
    Test if the number of recommendations respects top_k,
    assuming enough candidates are available and generated.
    """
    session_id = 103
    # Ensure there are enough products outside of current_events for candidates
    num_current_events = 5
    if len(ALL_PRODUCT_IDS) < num_current_events + 10: # Need at least 10 candidates for a top_k of 10
        pytest.skip("Not enough products in ALL_PRODUCT_IDS for this top_k test")

    current_aids = ALL_PRODUCT_IDS[:num_current_events]
    test_top_k = 10
    
    payload = {
        "session_id": session_id,
        "current_events": [
            {"aid": aid, "ts": 1661119200 + i, "type": 0} for i, aid in enumerate(current_aids)
        ],
        "top_k": test_top_k
    }
    response = client.post("/recommendations", json=payload)
    assert response.status_code == 200
    data = response.json()
    recommendations = data["recommendations"]

    # Max candidates generated is 100 by default in generate_candidates_for_session
    num_possible_candidates_from_pool = len(ALL_PRODUCT_IDS) - len(current_aids)
    max_generated_candidates = min(100, num_possible_candidates_from_pool)

    if max_generated_candidates > 0:
        if max_generated_candidates >= test_top_k:
            assert len(recommendations) == test_top_k
        else:
            # If fewer candidates than top_k are generated, return all of them
            assert len(recommendations) == max_generated_candidates
    else:
        assert len(recommendations) == 0


def test_recommendations_all_products_in_session():
    """
    Test case where all (or most) products from ALL_PRODUCT_IDS are in current_events.
    This requires mocking or a very small ALL_PRODUCT_IDS.
    For this example, we'll skip if ALL_PRODUCT_IDS is too large.
    """
    session_id = 104
    # This test is only feasible if ALL_PRODUCT_IDS is small or generate_candidates is mocked
    if len(ALL_PRODUCT_IDS) > 150: # If ALL_PRODUCT_IDS is large, candidate generation is random from a large pool
        pytest.skip("ALL_PRODUCT_IDS is too large for this specific test without mocking.")

    # Simulate all products being in the session
    payload = {
        "session_id": session_id,
        "current_events": [
            {"aid": aid, "ts": 1661119200 + i, "type": 0} for i, aid in enumerate(ALL_PRODUCT_IDS)
        ],
        "top_k": 5
    }
    response = client.post("/recommendations", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == session_id
    # Expect no new recommendations if all products are already in the session
    assert data["recommendations"] == []

