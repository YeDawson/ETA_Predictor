"""Unit tests for eta_model.py."""
from __future__ import annotations

import pytest

from eta_model import ETAModel


# ── Heuristic fallback (no model loaded) ──────────────────────────────────────

def test_predict_segment_heuristic_returns_positive(eta_model):
    t = eta_model.predict_segment(
        hour_of_day=9,
        day_of_week=1,
        road_type="primary",
        segment_length_m=1000.0,
        speed_limit_kmh=50.0,
        historical_avg_speed=40.0,
    )
    assert t > 0


def test_predict_segment_heuristic_known_value(eta_model):
    # 1000 m at 40 km/h = 90 s
    t = eta_model.predict_segment(
        hour_of_day=9,
        day_of_week=1,
        road_type="primary",
        segment_length_m=1000.0,
        speed_limit_kmh=50.0,
        historical_avg_speed=40.0,
    )
    assert t == pytest.approx(90.0, rel=1e-4)


def test_predict_segment_falls_back_to_speed_limit_when_historical_is_zero(eta_model):
    # historical = 0 → should use speed_limit_kmh (50 km/h) → 72 s
    t = eta_model.predict_segment(
        hour_of_day=9,
        day_of_week=1,
        road_type="motorway",
        segment_length_m=1000.0,
        speed_limit_kmh=50.0,
        historical_avg_speed=0.0,
    )
    assert t == pytest.approx(72.0, rel=1e-4)


def test_predict_segment_zero_speed_does_not_raise(eta_model):
    t = eta_model.predict_segment(
        hour_of_day=0,
        day_of_week=0,
        road_type="service",
        segment_length_m=200.0,
        speed_limit_kmh=0.0,
        historical_avg_speed=0.0,
    )
    assert t > 0


def test_predict_segment_short_segment(eta_model):
    t = eta_model.predict_segment(
        hour_of_day=12,
        day_of_week=3,
        road_type="residential",
        segment_length_m=50.0,
        speed_limit_kmh=30.0,
        historical_avg_speed=25.0,
    )
    assert 0 < t < 60   # short segment, should be under a minute


# ── predict_path ──────────────────────────────────────────────────────────────

def test_predict_path_sums_segments(eta_model):
    segments = [
        {"road_type": "primary",     "length": 1000.0, "speed_limit": 50.0, "historical_avg_speed": 40.0},
        {"road_type": "residential", "length": 500.0,  "speed_limit": 30.0, "historical_avg_speed": 25.0},
    ]
    total = eta_model.predict_path(segments, hour_of_day=9, day_of_week=1)
    # 1000/40 * 3.6 ks = 90 s  +  500/25 * 3.6 = 72 s  = 162 s
    assert total == pytest.approx(162.0, rel=1e-4)


def test_predict_path_empty_returns_zero(eta_model):
    assert eta_model.predict_path([], hour_of_day=9, day_of_week=1) == pytest.approx(0.0)


def test_predict_path_longer_route_takes_more_time(eta_model):
    short = [{"road_type": "primary", "length": 500.0,  "speed_limit": 50.0, "historical_avg_speed": 40.0}]
    long_ = [{"road_type": "primary", "length": 5000.0, "speed_limit": 50.0, "historical_avg_speed": 40.0}]
    assert eta_model.predict_path(long_, 9, 1) > eta_model.predict_path(short, 9, 1)


# ── Model loaded state ────────────────────────────────────────────────────────

def test_model_not_loaded_by_default():
    em = ETAModel()
    assert not em.is_loaded


def test_load_nonexistent_path_does_not_raise():
    em = ETAModel()
    em.load(path="/does/not/exist.pkl")
    assert not em.is_loaded
