import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from telemetry.reporter import round_to_grid  # noqa: E402


def test_round_to_grid_reduces_precision():
    grid_lat, grid_lon = round_to_grid(62.68, 26.35)
    assert grid_lat == 62.5
    assert grid_lon == 26.5


def test_round_to_grid_never_returns_exact_input_for_precise_coords():
    grid_lat, grid_lon = round_to_grid(61.0447, 28.1447)
    # Rounded value must differ from the raw input's sub-grid precision.
    assert grid_lat != 61.0447
    assert grid_lon != 28.1447


def test_round_to_grid_is_deterministic():
    a = round_to_grid(60.17, 24.94)
    b = round_to_grid(60.17, 24.94)
    assert a == b


def test_nearby_coords_collapse_to_same_grid_cell():
    """Two locations a few km apart should usually land on the same grid
    cell - this is the whole point of the anonymization."""
    a = round_to_grid(62.68, 26.35)
    b = round_to_grid(62.70, 26.38)
    assert a == b


def test_report_event_without_endpoint_is_a_safe_noop(monkeypatch):
    """No endpoint configured -> must not raise, must not need network."""
    from telemetry.reporter import report_event

    report_event(None, 62.0, 26.0, "wind_start")
    report_event("", 62.0, 26.0, "wind_start")
