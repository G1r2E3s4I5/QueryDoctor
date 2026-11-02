# backend/app/services/recommender.py
"""Recommendation engine for QueryDoctor.

This module defines a pure function that maps a model prediction and extracted
features to a list of structured recommendation dictionaries.  It **never**
executes SQL against the target database and does not modify any database
schema.

Each recommendation dictionary contains the following keys (JSON‑serialisable):

- ``recommendation_type`` – short identifier (e.g. ``index_suggestion``).
- ``title`` – human‑readable headline.
- ``description`` – detailed explanation of the suggested action.
- ``reason`` – why the recommendation was triggered (evidence).
- ``suggested_sql`` – optional DDL/SQL string (nullable).
- ``estimated_improvement_percent`` – optional numeric estimate.
- ``confidence`` – model‑estimated class probability (nullable).
- ``evidence`` – free‑form description of plan/feature evidence used.
- ``requires_approval`` – ``True`` for any DDL that changes the target DB.
- ``safety_notes`` – safety considerations for the DBA.

The function ``generate_recommendations`` is intended to be called by the
``/analyze-queries`` endpoint after a prediction has been obtained.
"""

from __future__ import annotations

from typing import List, Dict, Any, Optional

# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _quote_identifier(name: str) -> str:
    """Return a PostgreSQL‑safe quoted identifier.

    The function does **not** attempt to validate the identifier beyond simple
    character checks – callers must ensure the name is trusted (e.g. obtained
    from ``plan_json`` where the DB reports the exact table/column name).
    """
    safe_name = name.replace('"', '""')
    return f'"{safe_name}"'

# ---------------------------------------------------------------------------
# Core recommendation generation
# ---------------------------------------------------------------------------

def generate_recommendations(
    predicted_issue: str,
    model_probabilities: Optional[Dict[str, float]],
    features: Dict[str, float],
    query_text: str,
    plan_json: Any = None,
) -> List[Dict[str, Any]]:
    """Generate a list of recommendation dictionaries.

    Parameters
    ----------
    predicted_issue:
        One of ``needs_index``, ``query_rewrite``, ``full_table_scan`` or ``healthy``.
    model_probabilities:
        Mapping from class name to probability as returned by the ``predict``
        function (may be ``None``).
    features:
        Flat feature mapping produced by ``extract_features``.
    query_text:
        Original SQL string – used for simple heuristic checks.
    plan_json:
        Optional raw PostgreSQL plan JSON – used for evidence extraction.
    """
    recommendations: List[Dict[str, Any]] = []
    confidence: Optional[float] = None
    if model_probabilities and predicted_issue in model_probabilities:
        confidence = float(model_probabilities[predicted_issue])

    # -------------------------------------------------------------------
    # 1. needs_index
    # -------------------------------------------------------------------
    if predicted_issue == "needs_index":
        candidate_table: Optional[str] = None
        candidate_column: Optional[str] = None
        evidence_parts: List[str] = []
        if isinstance(plan_json, list) and plan_json:
            root = plan_json[0].get("Plan", {})
            nodes: List[Dict[str, Any]] = []
            def _collect(node: Dict[str, Any]):
                nodes.append(node)
                for sub in node.get("Plans", []):
                    _collect(sub)
            _collect(root)
            for node in nodes:
                if node.get("Node Type") == "Index Scan" and "Index Name" in node:
                    candidate_table = node.get("Relation Name")
                    cond = node.get("Index Cond") or ""
                    if "=" in cond:
                        left = cond.split("=")[0].strip().lstrip("(")
                        candidate_column = left
                        evidence_parts.append(f"Index Scan on {candidate_table} using column {candidate_column}")
                        break
                if "Filter" in node and not candidate_column:
                    filter_clause = node["Filter"]
                    for op in ["=", "<", ">", "LIKE"]:
                        if op in filter_clause:
                            left = filter_clause.split(op)[0].strip().lstrip("(")
                            candidate_column = left
                            candidate_table = node.get("Relation Name")
                            evidence_parts.append(f"Filter on {candidate_table}.{candidate_column}")
                            break
        if candidate_table and candidate_column:
            sql = (
                f"CREATE INDEX idx_{candidate_column}_on_{candidate_table} "
                f"ON {_quote_identifier(candidate_table)} ({_quote_identifier(candidate_column)});"
            )
            recommendations.append({
                "recommendation_type": "index_suggestion",
                "title": f"Create index on {candidate_table}.{candidate_column}",
                "description": "An index may speed up look‑ups for the filtered column.",
                "reason": "Model predicts a missing index and the plan shows a filter on this column.",
                "suggested_sql": sql,
                "estimated_improvement_percent": None,
                "confidence": confidence,
                "evidence": "; ".join(evidence_parts) or "No detailed plan evidence extracted.",
                "requires_approval": True,
                "safety_notes": "Indexes increase storage and write overhead; ensure the index is beneficial before applying.",
            })
        else:
            recommendations.append({
                "recommendation_type": "index_investigation",
                "title": "Investigate potential missing index",
                "description": "Review the query's filter/join columns and consider adding an index.",
                "reason": "Model predicted a missing index but column information could not be extracted safely.",
                "suggested_sql": None,
                "estimated_improvement_percent": None,
                "confidence": confidence,
                "evidence": "; ".join(evidence_parts) or "Insufficient plan detail.",
                "requires_approval": False,
                "safety_notes": "Adding an index should be verified against write patterns and table size.",
            })

    # -------------------------------------------------------------------
    # 2. query_rewrite
    # -------------------------------------------------------------------
    elif predicted_issue == "query_rewrite":
        if "*" in query_text.upper():
            recommendations.append({
                "recommendation_type": "column_projection",
                "title": "Avoid SELECT *",
                "description": "Specify only the columns required by the application.",
                "reason": "Model flagged inefficiency and the query uses SELECT *.",
                "suggested_sql": None,
                "estimated_improvement_percent": None,
                "confidence": confidence,
                "evidence": "Query uses wildcard column selection.",
                "requires_approval": False,
                "safety_notes": "Changing the column list may affect downstream code; verify required columns.",
            })
        else:
            recommendations.append({
                "recommendation_type": "query_simplification",
                "title": "Review query for simplification",
                "description": "Examine the query for redundant operations or sub‑queries.",
                "reason": "Model predicts the query could be rewritten for better performance.",
                "suggested_sql": None,
                "estimated_improvement_percent": None,
                "confidence": confidence,
                "evidence": "Model prediction without concrete plan evidence.",
                "requires_approval": False,
                "safety_notes": "Any rewrite must preserve semantics; test thoroughly.",
            })

    # -------------------------------------------------------------------
    # 3. full_table_scan
    # -------------------------------------------------------------------
    elif predicted_issue == "full_table_scan":
        seq_scan = features.get("seq_scan", 0)
        actual_rows = features.get("actual_rows")
        total_cost = features.get("total_cost")
        evidence: List[str] = []
        if seq_scan:
            evidence.append("Sequential scan detected.")
        if actual_rows is not None:
            evidence.append(f"Actual rows returned: {actual_rows}.")
        if total_cost is not None:
            evidence.append(f"Total cost: {total_cost}.")
        if seq_scan and features.get("filter_present"):
            recommendations.append({
                "recommendation_type": "index_investigation",
                "title": "Consider indexing filtered column(s)",
                "description": "A sequential scan with a filter may benefit from an index.",
                "reason": "Plan shows sequential scan with filter predicate.",
                "suggested_sql": None,
                "estimated_improvement_percent": None,
                "confidence": confidence,
                "evidence": " ".join(evidence),
                "requires_approval": False,
                "safety_notes": "Adding an index should be validated against write load.",
            })
        else:
            recommendations.append({
                "recommendation_type": "no_action",
                "title": "Sequential scan may be acceptable",
                "description": "Scanning the whole table is not inherently a problem if the table is small or the query returns most rows.",
                "reason": "Model predicted full_table_scan but evidence does not indicate a missing index.",
                "suggested_sql": None,
                "estimated_improvement_percent": None,
                "confidence": confidence,
                "evidence": " ".join(evidence),
                "requires_approval": False,
                "safety_notes": "Confirm that the scan is expected given the data distribution.",
            })

    # -------------------------------------------------------------------
    # 4. healthy
    # -------------------------------------------------------------------
    elif predicted_issue == "healthy":
        contradictions: List[str] = []
        if features.get("seq_scan") and features.get("filter_present"):
            contradictions.append("Sequential scan with filter detected.")
        if contradictions:
            recommendations.append({
                "recommendation_type": "caution",
                "title": "Potential hidden issue",
                "description": "Model says healthy but plan evidence shows possible inefficiency.",
                "reason": "; ".join(contradictions),
                "suggested_sql": None,
                "estimated_improvement_percent": None,
                "confidence": confidence,
                "evidence": "Plan features suggest further review.",
                "requires_approval": False,
                "safety_notes": "Manual review recommended.",
            })
        else:
            recommendations.append({
                "recommendation_type": "no_action",
                "title": "Query appears healthy",
                "description": "No immediate performance concerns detected.",
                "reason": "Model prediction aligns with plan evidence.",
                "suggested_sql": None,
                "estimated_improvement_percent": None,
                "confidence": confidence,
                "evidence": "Plan does not indicate costly operations.",
                "requires_approval": False,
                "safety_notes": "Continue monitoring query performance.",
            })

    # -------------------------------------------------------------------
    # 5. fallback for unknown categories
    # -------------------------------------------------------------------
    else:
        recommendations.append({
            "recommendation_type": "unknown",
            "title": "Unable to classify query",
            "description": "The prediction category is not recognized.",
            "reason": f"Received '{predicted_issue}'.",
            "suggested_sql": None,
            "estimated_improvement_percent": None,
            "confidence": confidence,
            "evidence": "N/A",
            "requires_approval": False,
            "safety_notes": "No automated recommendation can be provided.",
        })

    return recommendations
