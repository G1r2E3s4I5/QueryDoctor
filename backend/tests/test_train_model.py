# backend/tests/test_train_model.py
"""Tests for the ML training pipeline in ``train_model.py``.
These tests use monkey‑patching to avoid any real PostgreSQL connection or file I/O.
"""

import builtins
import json
import os
import sys
import uuid
from pathlib import Path
from unittest import mock

import pandas as pd
import pytest

# Import the module under test.
from backend.app.ml import train_model as tm

# Helper: synthetic workload records.
def _synthetic_records(labels):
    return [
        {
            "query_id": str(uuid.uuid4()),
            "query_template": "SELECT * FROM users WHERE id = $1",
            "query_category": "select",
            "expected_issue": label,
            "expected_reason": "synthetic",
            "parameters": [],
            "requires_manual_review": False,
        }
        for label in labels
    ]

# Helper: synthetic feature rows matching the workload ``query_id`` values.
def _synthetic_feature_rows(query_ids):
    rows = []
    for qid in query_ids:
        rows.append((qid, "seq_scan", 1.0))
        rows.append((qid, "index_scan", 0.0))
        rows.append((qid, "execution_time_ms", 12.5))
    return pd.DataFrame(rows, columns=["query_id", "feature_name", "feature_value"])


def test_load_dataset_success(monkeypatch):
    # Provide four records covering all VALID_LABELS.
    records = _synthetic_records(["needs_index", "query_rewrite", "full_table_scan", "healthy"])
    monkeypatch.setattr(tm, "load_workload_records", lambda limit=None: records)
    # Mock DB feature fetch to return matching rows.
    query_ids = [r["query_id"] for r in records]
    monkeypatch.setattr(tm, "_fetch_feature_rows", lambda ids: _synthetic_feature_rows(ids))

    X, y = tm._load_dataset()
    # Expect one row per record, and three feature columns (seq_scan, index_scan, execution_time_ms).
    assert len(X) == 4
    assert set(y) == set(["needs_index", "query_rewrite", "full_table_scan", "healthy"])
    assert all(col in X.columns for col in ["seq_scan", "index_scan", "execution_time_ms"])


def test_missing_label_classes(monkeypatch, capsys):
    # Only two labels present – training should abort.
    records = _synthetic_records(["needs_index", "healthy"])
    monkeypatch.setattr(tm, "load_workload_records", lambda limit=None: records)
    monkeypatch.setattr(tm, "_fetch_feature_rows", lambda ids: _synthetic_feature_rows(ids))
    with pytest.raises(SystemExit) as exc:
        tm.main()
    captured = capsys.readouterr()
    assert "Missing label classes" in captured.err
    assert exc.value.code == 1


def test_train_split_stratify(monkeypatch):
    # Four records, one per class – stratified split should succeed.
    records = _synthetic_records(["needs_index", "query_rewrite", "full_table_scan", "healthy"])
    monkeypatch.setattr(tm, "load_workload_records", lambda limit=None: records)
    monkeypatch.setattr(tm, "_fetch_feature_rows", lambda ids: _synthetic_feature_rows(ids))
    X, y = tm._load_dataset()
    X_train, X_test, y_train, y_test = tm._train_split(X, y)
    # With 4 examples and ratio 0.8 we expect 3 train, 1 test.
    assert len(X_train) == 3
    assert len(X_test) == 1
    # Stratification ensures at most one example per class in test.
    assert len(set(y_test)) == 1

