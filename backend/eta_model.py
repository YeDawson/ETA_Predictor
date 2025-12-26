"""
ETA Prediction Model
Wraps a trained XGBoost regressor that predicts segment travel time from
traffic features.  Falls back to a speed-limit heuristic when no model file
is present (e.g. during local development before training).
"""
from __future__ import annotations

import logging
import os
import pickle
from typing import List

import numpy as np

logger = logging.getLogger(__name__)

MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "eta_model.pkl")

# Encoding must match the one used during training (train_eta_model.ipynb)
ROAD_TYPE_ENCODING: dict[str, int] = {
    "motorway":     0,
    "trunk":        1,
    "primary":      2,
    "secondary":    3,
    "tertiary":     4,
    "residential":  5,
    "unclassified": 6,
    "service":      7,
}
FALLBACK_ROAD_TYPE = 6   # unclassified

FEATURE_ORDER = [
    "hour_of_day",
    "day_of_week",
    "road_type_enc",
    "segment_length_m",
    "speed_limit_kmh",
    "historical_avg_speed",
]


class ETAModel:
    """Load a pickled sklearn-compatible model and run inference."""

    def __init__(self) -> None:
        self._model = None
        self._loaded = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def load(self, path: str = MODEL_PATH) -> None:
        if os.path.exists(path):
            with open(path, "rb") as fh:
                self._model = pickle.load(fh)
            self._loaded = True
            logger.info("ETA model loaded from %s", path)
        else:
            logger.warning(
                "No trained model at %s — using speed-limit heuristic. "
                "Run notebooks/train_eta_model.ipynb to train.",
                path,
            )

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def predict_segment(
        self,
        *,
        hour_of_day: int,
        day_of_week: int,
        road_type: str,
        segment_length_m: float,
        speed_limit_kmh: float,
        historical_avg_speed: float,
    ) -> float:
        """Return predicted travel time in seconds for one road segment."""
        if self._loaded and self._model is not None:
            road_type_enc = ROAD_TYPE_ENCODING.get(road_type, FALLBACK_ROAD_TYPE)
            X = np.array([[
                hour_of_day,
                day_of_week,
                road_type_enc,
                segment_length_m,
                speed_limit_kmh,
                historical_avg_speed,
            ]], dtype=np.float32)
            return float(self._model.predict(X)[0])

        # Heuristic fallback: use historical speed if plausible, else speed limit
        speed = historical_avg_speed if historical_avg_speed > 1.0 else speed_limit_kmh
        if speed <= 0:
            speed = 30.0
        return (segment_length_m / 1000.0) / speed * 3600.0

    def predict_path(
        self,
        segments: List[dict],
        hour_of_day: int,
        day_of_week: int,
    ) -> float:
        """
        Predict total travel time for an ordered list of road segments.

        Each segment dict must contain:
            road_type          (str)
            length             (float, metres)
            speed_limit        (float, km/h)
            historical_avg_speed (float, km/h)
        """
        total = 0.0
        for seg in segments:
            total += self.predict_segment(
                hour_of_day=hour_of_day,
                day_of_week=day_of_week,
                road_type=seg.get("road_type", "unclassified"),
                segment_length_m=seg.get("length", 100.0),
                speed_limit_kmh=seg.get("speed_limit", 50.0),
                historical_avg_speed=seg.get("historical_avg_speed", 0.0),
            )
        return total
