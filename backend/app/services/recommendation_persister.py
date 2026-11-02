# backend/app/services/recommendation_persister.py
"""Utility to persist recommendation dictionaries into the project database.

The ``recommendations`` table (see ``schema.sql``) only stores a subset of the
information produced by ``recommender.generate_recommendations``:

- ``suggestion`` – free‑text description (concatenation of title and description).
- ``rewritten_sql`` – optional DDL/SQL string.
- ``confidence`` – numeric probability if available.

Any additional keys (e.g. ``evidence``, ``requires_approval``) are returned to the
API client but are **not** written to the database to avoid silent schema changes.
"""

from __future__ import annotations

from typing import List, Dict, Any

from ..db.connection import get_project_connection


def persist_recommendations(result_id: int, recommendations: List[Dict[str, Any]]) -> None:
    """Insert a list of recommendation dictionaries for a given analysis result.

    Parameters
    ----------
    result_id:
        Primary key of the ``analysis_results`` record the recommendations belong to.
    recommendations:
        List of dictionaries as produced by ``recommender.generate_recommendations``.
    """
    if not recommendations:
        return

    insert_sql = (
        "INSERT INTO recommendations (result_id, suggestion, rewritten_sql, confidence) "
        "VALUES (%s, %s, %s, %s)"
    )
    with get_project_connection() as conn:
        cur = conn.cursor()
        for rec in recommendations:
            suggestion = f"{rec.get('title', '')}: {rec.get('description', '')}".strip()
            rewritten_sql = rec.get('suggested_sql')
            confidence = rec.get('confidence')
            cur.execute(insert_sql, (result_id, suggestion, rewritten_sql, confidence))
        conn.commit()
