"""Recommend spots that suit the current wind direction.

Each spot lists the wind direction ranges it works in (e.g. "300-350",
"325-15" wraps over north), as published on surffikamu.fi. A spot is
recommended when the measured direction falls inside one of its ranges;
spots where the direction sits in the middle of a range rank above ones
where it is right at the edge, and favorites rank above everything else.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .config import SpotConfig

# Closer than this to a range edge = direction is "borderline" for the spot.
EDGE_MARGIN_DEG = 10.0


@dataclass
class SpotMatch:
    spot: SpotConfig
    centrality: float  # 0.0 = at range edge, 1.0 = exactly mid-range
    margin_deg: float  # degrees to the nearest range edge

    @property
    def borderline(self) -> bool:
        return self.margin_deg < EDGE_MARGIN_DEG


def _match_range(direction_deg: float, start: float, end: float) -> Optional[tuple[float, float]]:
    """Return (centrality, margin) if direction is inside start->end
    (clockwise, wrapping over 360), else None."""
    width = (end - start) % 360
    offset = (direction_deg - start) % 360
    if offset > width:
        return None
    margin = min(offset, width - offset)
    half = width / 2
    return (margin / half if half else 1.0), margin


def match_spot(spot: SpotConfig, direction_deg: float) -> Optional[SpotMatch]:
    best: Optional[SpotMatch] = None
    for start, end in spot.direction_ranges:
        result = _match_range(direction_deg, start, end)
        if result and (best is None or result[0] > best.centrality):
            best = SpotMatch(spot=spot, centrality=result[0], margin_deg=result[1])
    return best


def recommend_spots(
    spots: list[SpotConfig],
    direction_deg: Optional[float],
    favorites_only: bool = False,
) -> list[SpotMatch]:
    if direction_deg is None:
        return []
    candidates = [s for s in spots if s.favorite or not favorites_only]
    matches = [m for m in (match_spot(s, direction_deg) for s in candidates) if m]
    matches.sort(key=lambda m: (not m.spot.favorite, m.borderline, -m.centrality))
    return matches


def format_ranges(spot: SpotConfig) -> str:
    return ", ".join(f"{start:g}-{end:g}°" for start, end in spot.direction_ranges)


def spots_summary(
    spots: list[SpotConfig],
    direction_deg: Optional[float],
    max_listed: int = 3,
    favorites_only: bool = False,
) -> Optional[str]:
    """Message section listing the best spots for this direction, with links."""
    if not spots or direction_deg is None:
        return None

    matches = recommend_spots(spots, direction_deg, favorites_only)
    if not matches:
        return "📍 Tälle tuulensuunnalle ei löytynyt sopivaa spottia listaltasi."

    lines = [f"📍 Parhaat spotit suunnalle {direction_deg:.0f}°:"]
    for i, m in enumerate(matches[:max_listed], start=1):
        star = "⭐ " if m.spot.favorite else ""
        edge = " - suunta rajoilla" if m.borderline else ""
        lines.append(f"{i}. {star}{m.spot.name} ({format_ranges(m.spot)}){edge}")
        if m.spot.url:
            lines.append(f"   {m.spot.url}")
    return "\n".join(lines)
