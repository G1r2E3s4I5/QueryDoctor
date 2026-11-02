# backend/app/ml/predict.py
"""Inference utilities for QueryDoctor Random Forest model.

The module provides a single ``predict`` function that loads the trained pipeline
and its accompanying metadata, validates the provided feature dictionary, and
returns the predicted class along with the model version. If the pipeline
supports probability estimates (i.e. ``predict_proba``), those are also returned
as a mapping from class name to probability.

All I/O is performed safely – missing model files raise a clear ``RuntimeError``
so callers can handle the situation gracefully.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, Any

try:
    import joblib
except ImportError:  # pragma: no cover
    def _missing_joblib(*args, **kwargs):
        raise RuntimeError("joblib is required for model loading but is not installed.")
    joblib = type('joblib', (), {'load': _missing_joblib})

try:
    import pandas as pd
except ImportError:  # pragma: no cover
    def _missing_pd(*args, **kwargs):
        raise RuntimeError("pandas is required for model inference but is not installed.")
    pd = type('pandas', (), {'DataFrame': _missing_pd})

# Paths are relative to this file – tests may monkey‑patch these attributes.
MODEL_PATH = Path(__file__).with_name("model.pkl")
METADATA_PATH = Path(__file__).with_name("model_metadata.json")


def _load_pipeline() -> Any:
    """Load the serialized scikit‑learn pipeline.

    Raises:
        RuntimeError: If the model file does not exist.
    """
    if not MODEL_PATH.exists():
        raise RuntimeError("Trained model file not found at {}".format(MODEL_PATH))
    return joblib.load(str(MODEL_PATH))


def _load_metadata() -> Dict[str, Any]:
    """Load the JSON metadata accompanying the model.

    Raises:
        RuntimeError: If the metadata file is missing or cannot be parsed.
    """
    if not METADATA_PATH.exists():
        raise RuntimeError("Model metadata file not found at {}".format(METADATA_PATH))
    try:
        with METADATA_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        raise RuntimeError(f"Failed to read model metadata: {exc}") from exc


def predict(feature_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Run inference on a single feature record.

    Parameters
    ----------
    feature_dict:
        Mapping of feature names to numeric values. Missing features will be
        treated as ``NaN`` and handled by the pipeline's imputer.

    Returns
    -------
    dict
        ``{"prediction": <class>, "model_version": <str>, "probabilities": {...}}``
        The ``probabilities`` key is present only when the underlying model
        implements ``predict_proba``.
    """
    pipeline = _load_pipeline()
    metadata = _load_metadata()

    # Convert to a DataFrame – this automatically aligns any missing columns as NaN.
    X = pd.DataFrame([feature_dict])
    try:
        pred = pipeline.predict(X)[0]
    except Exception as exc:
        raise RuntimeError(f"Model prediction failed: {exc}") from exc

    result: Dict[str, Any] = {
        "prediction": pred,
        "model_version": metadata.get("model_version"),
    }

    # Attach probability estimates if available.
    if hasattr(pipeline, "predict_proba"):
        try:
            prob_array = pipeline.predict_proba(X)[0]
            # Map class names (as stored in the estimator) to probabilities.
            class_names = getattr(pipeline.named_steps["rf"], "classes_", [])
            result["probabilities"] = {str(cls): float(p) for cls, p in zip(class_names, prob_array)}
        except Exception as exc:
            # Non‑critical – continue without probabilities.
            print(f"[WARN] Failed to obtain prediction probabilities: {exc}", file=sys.stderr)
    return result
