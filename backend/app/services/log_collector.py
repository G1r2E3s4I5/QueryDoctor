# backend/app/services/log_collector.py
"""Log collection and workload parsing utilities.

Two input sources are supported:

1. **Generated workload** – the JSON‑Lines file produced by
   ``backend/scripts/generate_bad_queries.py``.  Each line must contain the
   fields documented in the Phase 3 specification.
2. **PostgreSQL slow‑query logs** – a placeholder implementation that raises a
   ``NotImplementedError`` because the exact log format varies between setups.

The public function ``load_workload_records`` reads the workload file, validates
each record, and returns a list of dictionaries ready for further processing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Dict, Any

# Expected keys for a workload record (Phase 3 contract).
_REQUIRED_FIELDS = [
    "query_id",
    "query_template",
    "query_category",
    "expected_issue",
    "expected_reason",
    "parameters",
    "requires_manual_review",
]

_WORKLOAD_PATH = Path(__file__).resolve().parents[3] / "data" / "workload" / "query_templates.jsonl"


class LogCollectorError(RuntimeError):
    """Base exception for log‑collector related problems."""


def _validate_record(record: Dict[str, Any]) -> None:
    """Validate a single workload record.

    Raises:
        LogCollectorError: If a required field is missing or has an unexpected type.
    """
    missing = [f for f in _REQUIRED_FIELDS if f not in record]
    if missing:
        raise LogCollectorError(f"Record missing required fields: {missing}")
    # Simple type checks – more thorough validation can be added later.
    if not isinstance(record["requires_manual_review"], bool):
        raise LogCollectorError("'requires_manual_review' must be a boolean")
    if not isinstance(record["parameters"], (list, dict)):
        raise LogCollectorError("'parameters' must be a list or dict")


def load_workload_records(limit: int | None = None) -> List[Dict[str, Any]]:
    """Load and validate records from the generated workload file.

    Args:
        limit: Optional maximum number of records to return.
    Returns:
        A list of validated workload dictionaries.
    Raises:
        LogCollectorError: If the file cannot be read or a record is invalid.
    """
    if not _WORKLOAD_PATH.exists():
        raise LogCollectorError(f"Workload file not found at {_WORKLOAD_PATH}")
    records: List[Dict[str, Any]] = []
    with _WORKLOAD_PATH.open("r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise LogCollectorError(f"Invalid JSON on line {line_no}: {exc}") from exc
            _validate_record(rec)
            records.append(rec)
            if limit is not None and len(records) >= limit:
                break
    return records


def parse_pg_slow_query_log(_log_path: Path) -> List[Dict[str, Any]]:  # pragma: no cover
    """Parse a PostgreSQL slow‑query log file.

    The exact format varies per ``log_line_prefix`` configuration, so this
    function is deliberately left unimplemented.  It raises ``NotImplementedError``
    to make the limitation explicit to callers.
    """
    raise NotImplementedError(
        "Parsing arbitrary PostgreSQL log files is not supported in Phase 4."
    )
