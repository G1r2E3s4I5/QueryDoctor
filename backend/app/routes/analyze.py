# backend/app/routes/analyze.py
"""FastAPI endpoints for query analysis ingestion.

Provides a health check and a POST endpoint that processes generated workload records,
validates them, optionally executes safe SELECT queries on the target database,
extracts execution‑plan features, and stores results in the QueryDoctor project database.
"""

from __future__ import annotations

from typing import Dict, Any, List
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
import json, sys

from ..services.log_collector import load_workload_records, LogCollectorError
from ..services.feature_extractor import extract_features
from ..db.connection import get_project_connection, get_target_connection

router = APIRouter()


class AnalyzeRequest(BaseModel):
    """Request body for ``/analyze-queries``.

    * ``batch_size`` – optional limit on how many workload records to process.
    * ``execute`` – whether to run ``EXPLAIN ANALYZE`` (collect actual runtime
      metrics). Default ``False`` for safe dry‑run.
    """

    batch_size: int | None = Field(default=None, ge=1, description="Maximum records to process")
    execute: bool = Field(default=False, description="Collect actual runtime metrics via EXPLAIN ANALYZE")


PROHIBITED_KEYWORDS = {"INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "GRANT", "REVOKE", "TRUNCATE"}


def _is_safe_select(query: str) -> bool:
    """Validate that the query is a simple SELECT.

    * Must start with ``SELECT`` after optional whitespace (case‑insensitive).
    * Must not contain a semicolon which could terminate the statement.
    * Must not contain any prohibited keywords.
    """
    stripped = query.lstrip()
    if not stripped[:6].upper() == "SELECT":
        return False
    if ";" in stripped:
        return False
    upper = stripped.upper()
    return not any(kw in upper for kw in PROHIBITED_KEYWORDS)


@router.get("/health", tags=["health"])
def health_check() -> Dict[str, str]:
    return {"status": "ok"}


@router.post("/analyze-queries", tags=["analysis"])
def analyze_queries(req: AnalyzeRequest) -> Dict[str, Any]:
    try:
        records = load_workload_records(limit=req.batch_size)
    except LogCollectorError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    total = len(records)
    successful = 0
    rejected = 0
    failed = 0
    actual_plan_collected = 0

    for rec in records:
        if rec.get("requires_manual_review"):
            rejected += 1
            continue
        query_template: str = rec["query_template"]
        parameters = rec.get("parameters") or []
        if not _is_safe_select(query_template):
            rejected += 1
            continue
        plan_json: Any = None
        if req.execute:
            try:
                with get_target_connection() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {query_template}",
                        tuple(parameters) if isinstance(parameters, list) else parameters,
                    )
                    plan_json = cur.fetchone()[0]
                actual_plan_collected += 1
            except Exception:
                failed += 1
                continue
        features = extract_features(plan_json) if plan_json else {}
        try:
            with get_project_connection() as proj_conn:
                cur = proj_conn.cursor()
                cur.execute(
                    "INSERT INTO analyzed_queries (query_text, target_db, execution_time_ms) VALUES (%s, %s, %s) RETURNING query_id",
                    (query_template, "target", features.get("execution_time_ms")),
                )
                query_id = cur.fetchone()[0]
                for name, value in features.items():
                    cur.execute(
                        "INSERT INTO query_features (query_id, feature_name, feature_value) VALUES (%s, %s, %s)",
                        (query_id, name, value),
                    )
            successful += 1
        except Exception:
            failed += 1
            continue

    return {
        "total_records": total,
        "successful": successful,
        "rejected": rejected,
        "failed": failed,
        "actual_plan_collected": actual_plan_collected,
    }

@router.post("/recommendations", tags=["analysis"])
def generate_recommendations_endpoint(query_id: str) -> Dict[str, Any]:
    """Generate and persist recommendations for a given analyzed query.

    Steps:
    1. Load extracted features for the query.
    2. Run model prediction.
    3. Create recommendations.
    4. Persist them linked to a new analysis_results record.
    """
    # Imports are performed inside the function to allow test monkeypatching of these utilities.
    # Feature extractor
    from ..services.feature_extractor import extract_features
    # Database connections
    from ..db.connection import get_target_connection, get_project_connection
    # ML prediction
    from ..ml.predict import predict as ml_predict
    # Recommendation generator
    from ..services.recommender import generate_recommendations as gen_recs
    # Persistence
    from ..services.recommendation_persister import persist_recommendations
    # Fetch a sample plan for the query if needed (optional)
    plan_json = None
    try:
        with get_target_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT query_text FROM analyzed_queries WHERE query_id = %s", (query_id,))
            row = cur.fetchone()
            if row:
                query_text = row[0]
            else:
                raise HTTPException(status_code=404, detail="Query not found")
            # Attempt to get a plan (may be None if not previously collected)
            cur.execute("SELECT plan_json FROM analysis_results WHERE query_id = %s LIMIT 1", (query_id,))
            plan_row = cur.fetchone()
            if plan_row:
                plan_json = plan_row[0]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    # Extract features (if plan not available, use empty dict)
    features = extract_features(plan_json) if plan_json else {}
    # Predict
    pred_result = ml_predict(features)
    predicted_issue = pred_result.get("prediction")
    probabilities = pred_result.get("probabilities")
    model_version = pred_result.get("model_version")
    # Insert analysis_results record
    with get_project_connection() as proj_conn:
        cur = proj_conn.cursor()
        cur.execute(
            "INSERT INTO analysis_results (query_id, model_version, plan_json, status) VALUES (%s, %s, %s, %s) RETURNING result_id",
            (query_id, model_version, json.dumps(plan_json) if plan_json else None, "completed"),
        )
        result_id = cur.fetchone()[0]
    # Generate recommendations
    recommendations = gen_recs(predicted_issue, probabilities, features, query_text, plan_json)
    # Persist
    persist_recommendations(result_id, recommendations)
    return {"result_id": result_id, "recommendations": recommendations}

@router.get("/suggestions", tags=["analysis"])
def get_suggestions(result_id: int) -> List[Dict[str, Any]]:
    """Retrieve persisted recommendations for a given analysis result.
    """
    with get_project_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT rec_id, suggestion, rewritten_sql, confidence FROM recommendations WHERE result_id = %s",
            (result_id,),
        )
        rows = cur.fetchall()
    return [
        {
            "rec_id": r[0],
            "suggestion": r[1],
            "rewritten_sql": r[2],
            "confidence": r[3],
        }
        for r in rows
    ]



