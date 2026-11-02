# backend/app/ml/train_model.py
"""Training pipeline for QueryDoctor Random Forest model.

The script builds a reproducible dataset from the project database and the
synthetic workload file, trains a scikit‑learn ``Pipeline`` consisting of a
``SimpleImputer`` and a ``RandomForestClassifier``, evaluates the model, and
stores the trained pipeline together with metadata.

Running the module as a script (``python -m backend.app.ml.train_model``) will
execute the full end‑to‑end training process.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    precision_recall_fscore_support,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

# Local imports – monkey‑patchable in tests.
from ..services.log_collector import load_workload_records, LogCollectorError
from ..db.connection import get_project_connection

# ---------------------------------------------------------------------------
# Configuration constants (can be overridden via env vars for flexibility).
# ---------------------------------------------------------------------------
MODEL_PATH = Path(__file__).with_name("model.pkl")
METADATA_PATH = Path(__file__).with_name("model_metadata.json")
RANDOM_SEED = int(os.getenv("QUERYDOCTOR_TRAIN_SEED", "42"))
TRAIN_TEST_RATIO = float(os.getenv("QUERYDOCTOR_TRAIN_RATIO", "0.8"))
# Expected label values – any record with a different ``expected_issue`` will be
# ignored for training purposes.
VALID_LABELS = {"needs_index", "query_rewrite", "full_table_scan", "healthy"}

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------
def _fetch_feature_rows(query_ids: List[str]) -> pd.DataFrame:
    """Return feature rows for the supplied ``query_ids``.

    The result has columns ``query_id``, ``feature_name`` and ``feature_value``.
    """
    placeholder = ",".join(["%s"] * len(query_ids))
    sql = (
        "SELECT query_id, feature_name, feature_value "
        f"FROM query_features WHERE query_id IN ({placeholder})"
    )
    with get_project_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(query_ids))
            rows = cur.fetchall()
    # rows is a list of tuples (query_id, feature_name, feature_value)
    return pd.DataFrame(rows, columns=["query_id", "feature_name", "feature_value"])


def _pivot_features(df: pd.DataFrame) -> pd.DataFrame:
    """Convert long ``query_features`` rows to a wide feature matrix.

    Missing features for a given ``query_id`` will result in ``NaN`` values –
    they are later imputed.
    """
    if df.empty:
        return pd.DataFrame()
    pivot = df.pivot(index="query_id", columns="feature_name", values="feature_value")
    # Reset index to make ``query_id`` a column again.
    pivot.reset_index(inplace=True)
    return pivot


def _load_dataset() -> Tuple[pd.DataFrame, pd.Series]:
    """Load a training dataset and return ``X`` (features) and ``y`` (labels).

    The workflow is:
    1. Load workload records (they contain ``query_id`` and ``expected_issue``).
    2. Filter to records whose ``expected_issue`` is one of ``VALID_LABELS``.
    3. Fetch stored features for the retained ``query_id`` values.
    4. Pivot features to a wide table and align with the workload records.
    5. Return the feature matrix ``X`` and the label series ``y``.
    """
    try:
        records = load_workload_records()
    except LogCollectorError as exc:
        raise RuntimeError(f"Failed to load workload records: {exc}") from exc

    # Build a DataFrame from the workload records.
    workload_df = pd.DataFrame(records)
    # Keep only rows with a supported label.
    workload_df = workload_df[workload_df["expected_issue"].isin(VALID_LABELS)].copy()
    if workload_df.empty:
        raise RuntimeError("No workload records with a valid label were found.")

    query_ids = workload_df["query_id"].astype(str).tolist()
    feature_long_df = _fetch_feature_rows(query_ids)
    feature_wide_df = _pivot_features(feature_long_df)

    # Merge on ``query_id`` – inner join ensures we only keep records that have
    # extracted features.
    merged = pd.merge(workload_df[["query_id", "expected_issue"]], feature_wide_df, on="query_id", how="inner")
    if merged.empty:
        raise RuntimeError("Feature extraction yielded no rows matching workload records.")

    X = merged.drop(columns=["query_id", "expected_issue"])
    y = merged["expected_issue"]
    return X, y


def _train_split(X: pd.DataFrame, y: pd.Series) -> Tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
    """Deterministically split the data.

    Uses ``RANDOM_SEED`` and ``TRAIN_TEST_RATIO``. If each class has at least two
    examples we perform stratified splitting; otherwise we fall back to a simple
    random split and issue a warning.
    """
    # Determine if stratification is possible.
    class_counts = y.value_counts()
    can_stratify = (class_counts >= 2).all()
    if can_stratify:
        return train_test_split(
            X,
            y,
            test_size=1 - TRAIN_TEST_RATIO,
            random_state=RANDOM_SEED,
            stratify=y,
        )
    else:
        # No stratification – log a warning via stdout (tests can capture).
        print("[WARN] Insufficient examples per class for stratified split; using random split.", file=sys.stderr)
        return train_test_split(
            X,
            y,
            test_size=1 - TRAIN_TEST_RATIO,
            random_state=RANDOM_SEED,
            stratify=None,
        )


def _build_pipeline() -> Pipeline:
    """Create a scikit‑learn ``Pipeline`` with imputation and RandomForest.

    Hyper‑parameters are deliberately simple and documented.
    """
    imputer = SimpleImputer(strategy="median")
    rf = RandomForestClassifier(
        n_estimators=200,
        max_depth=None,
        random_state=RANDOM_SEED,
        n_jobs=-1,
        class_weight="balanced",
    )
    return Pipeline([("imputer", imputer), ("rf", rf)])


def _evaluate_model(pipeline: Pipeline, X_test: pd.DataFrame, y_test: pd.Series) -> Dict[str, any]:
    """Compute evaluation metrics.

    Returns a dictionary that can be serialised to JSON for metadata storage.
    """
    y_pred = pipeline.predict(X_test)
    accuracy = accuracy_score(y_test, y_pred)
    precision, recall, f1, _ = precision_recall_fscore_support(
        y_test, y_pred, labels=sorted(VALID_LABELS), zero_division=0
    )
    report = classification_report(
        y_test, y_pred, labels=sorted(VALID_LABELS), output_dict=True, zero_division=0
    )
    cm = confusion_matrix(y_test, y_pred, labels=sorted(VALID_LABELS)).tolist()
    return {
        "accuracy": accuracy,
        "macro_precision": float(np.mean(precision)),
        "macro_recall": float(np.mean(recall)),
        "macro_f1": float(np.mean(f1)),
        "per_class": report,
        "confusion_matrix": cm,
    }


def _save_artifacts(pipeline: Pipeline, metadata: Dict[str, any]):
    """Save the model pipeline and metadata atomically.

    Writes to a temporary file within the same directory and then renames it –
    this avoids corrupting an existing model if something goes wrong during
    serialization.
    """
    # ----- Model -----
    with tempfile.NamedTemporaryFile(delete=False, dir=MODEL_PATH.parent) as tmp_model:
        joblib.dump(pipeline, tmp_model.name)
    os.replace(tmp_model.name, MODEL_PATH)

    # ----- Metadata -----
    metadata_json = json.dumps(metadata, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=METADATA_PATH.parent, encoding="utf-8") as tmp_meta:
        tmp_meta.write(metadata_json)
    os.replace(tmp_meta.name, METADATA_PATH)


def main() -> None:
    """Execute the full training pipeline.

    The function prints a brief summary to stdout and writes model files to the
    repository. It aborts early with a clear message if the dataset is not
    sufficient for a defensible four‑class model.
    """
    print("[INFO] Loading dataset …")
    X, y = _load_dataset()
    # Verify class coverage.
    missing = VALID_LABELS - set(y.unique())
    if missing:
        print(
            f"[ERROR] Missing label classes {missing}. Cannot train a four‑class model.",
            file=sys.stderr,
        )
        sys.exit(1)

    X_train, X_test, y_train, y_test = _train_split(X, y)
    print(f"[INFO] Train/Test split: {len(X_train)} / {len(X_test)} examples")

    pipeline = _build_pipeline()
    pipeline.fit(X_train, y_train)

    metrics = _evaluate_model(pipeline, X_test, y_test)
    # Assemble metadata.
    metadata = {
        "model_version": str(uuid.uuid4()),
        "trained_at": datetime.utcnow().isoformat() + "Z",
        "feature_names": list(X.columns),
        "label_classes": sorted(list(VALID_LABELS)),
        "train_count": len(X_train),
        "test_count": len(X_test),
        "random_seed": RANDOM_SEED,
        "library_versions": {
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scikit-learn": "{0}".format(".".join(map(str, __import__('sklearn').__version__.split('.')))),
        },
        "evaluation": metrics,
    }

    _save_artifacts(pipeline, metadata)
    print("[INFO] Training complete. Model saved to", MODEL_PATH)
    print("[INFO] Metadata saved to", METADATA_PATH)
    # Print a concise evaluation summary.
    print(f"[RESULT] Accuracy: {metrics['accuracy']:.3f}, Macro F1: {metrics['macro_f1']:.3f}")


if __name__ == "__main__":
    main()

