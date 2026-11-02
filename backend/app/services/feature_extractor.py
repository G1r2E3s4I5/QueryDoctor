# backend/app/services/feature_extractor.py
"""Feature extraction from PostgreSQL JSON execution plans.

The function ``extract_features`` walks the JSON plan (as returned by
``EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)``) and collects a flat mapping of
feature names to numeric values.  All extracted values are ``float`` so they can
be stored directly in the ``query_features`` table which expects a ``FLOAT``.

Features currently extracted (subject to availability in the plan):
- execution_time_ms
- planning_time_ms
- total_cost
- actual_rows
- actual_loops
- shared_hit_blocks
- shared_read_blocks
- seq_scan (1 if any Sequential Scan node exists, otherwise 0)
- index_scan (1 if any Index Scan node exists, otherwise 0)
- index_name (hash of the index name – stored as a numeric identifier)
- join_count (number of Join nodes)
- filter_present (1 if any node contains a filter clause)

If a feature is missing the function simply omits it; callers must handle the
absence gracefully.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List


def _traverse_plan(plan: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Recursively collect all plan nodes.

    ``plan`` is the list under the top‑level ``"Plan"`` key returned by PostgreSQL.
    The function returns a flat list of all nodes for easier analysis.
    """
    nodes: List[Dict[str, Any]] = []
    for node in plan:
        nodes.append(node)
        # Nested subplans are under the "Plans" key.
        if "Plans" in node and isinstance(node["Plans"], list):
            nodes.extend(_traverse_plan(node["Plans"]))
    return nodes


def _hash_index_name(name: str) -> float:
    """Return a deterministic numeric hash for an index name.

    The hash is deterministic across runs and fits into a ``float`` column.
    """
    # Use SHA‑256 and convert the first 8 bytes to an integer.
    digest = hashlib.sha256(name.encode()).digest()[:8]
    return float(int.from_bytes(digest, "big"))


def extract_features(plan_json: Any) -> Dict[str, float]:
    """Extract numeric features from a PostgreSQL JSON execution plan.

    ``plan_json`` is the raw Python object returned by ``psycopg`` when fetching
    the JSON plan column.  It is typically a list with a single dict containing
    ``"Plan"`` and optional top‑level timing fields.
    """
    if not isinstance(plan_json, list) or not plan_json:
        return {}
    top = plan_json[0]
    features: Dict[str, float] = {}

    # Top‑level timing information.
    if "Planning Time" in top:
        features["planning_time_ms"] = float(top["Planning Time"])
    if "Execution Time" in top:
        features["execution_time_ms"] = float(top["Execution Time"])
    if "Total Cost" in top:
        features["total_cost"] = float(top["Total Cost"])

    # Walk the plan nodes.
    root_plan = top.get("Plan")
    if not isinstance(root_plan, dict):
        return features
    nodes = _traverse_plan([root_plan])

    seq_scan = 0
    index_scan = 0
    join_count = 0
    filter_present = 0
    shared_hit_blocks = 0.0
    shared_read_blocks = 0.0
    actual_rows_total = 0.0
    actual_loops_total = 0.0
    index_names: List[str] = []

    for node in nodes:
        node_type = node.get("Node Type", "")
        if node_type == "Seq Scan":
            seq_scan = 1
        if node_type == "Index Scan":
            index_scan = 1
            if "Index Name" in node:
                index_names.append(node["Index Name"])
        if "Join" in node_type:
            join_count += 1
        if "Filter" in node:
            filter_present = 1
        # Buffers block counts – they may be missing.
        if "Shared Hit Blocks" in node:
            shared_hit_blocks += float(node["Shared Hit Blocks"])
        if "Shared Read Blocks" in node:
            shared_read_blocks += float(node["Shared Read Blocks"])
        if "Actual Rows" in node:
            actual_rows_total += float(node["Actual Rows"])
        if "Actual Loops" in node:
            actual_loops_total += float(node["Actual Loops"])

    # Populate aggregated features.
    features["seq_scan"] = float(seq_scan)
    features["index_scan"] = float(index_scan)
    features["join_count"] = float(join_count)
    features["filter_present"] = float(filter_present)
    if shared_hit_blocks:
        features["shared_hit_blocks"] = shared_hit_blocks
    if shared_read_blocks:
        features["shared_read_blocks"] = shared_read_blocks
    if actual_rows_total:
        features["actual_rows"] = actual_rows_total
    if actual_loops_total:
        features["actual_loops"] = actual_loops_total
    if index_names:
        # Use the first index name for hashing – multiple indexes are rare.
        features["index_name_hash"] = _hash_index_name(index_names[0])

    return features
