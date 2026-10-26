"""Generate a wind chart image to attach to alerts (v0.3, optional).

Uses matplotlib with the non-interactive "Agg" backend so it works
headless - no display needed, works fine on GitHub Actions runners,
Raspberry Pis, or any server.

This is deliberately opt-in (chart.enabled: false by default) because
matplotlib is a heavier dependency and image generation adds a few
seconds to every run - fine for most setups, but worth letting people
skip it if they just want fast, minimal text alerts.
"""
from __future__ import annotations

import math
from typing import Optional, Sequence
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

from .config import WindConfig  # noqa: E402
from .models import ForecastPoint, WindReading, deg_to_compass  # noqa: E402
from .open_meteo import ATTRIBUTION, model_label  # noqa: E402

# FMI only covers Finland, so local time is always Finnish time.
LOCAL_TZ = ZoneInfo("Europe/Helsinki")

# Windy-style colour steps for wind speed (m/s): (lower bound, colour).
WIND_COLOURS = [
    (0.0, "#9ecae1"),
    (3.0, "#6baed6"),
    (5.0, "#4fc3a1"),
    (7.0, "#5cc85c"),
    (9.0, "#b5d334"),
    (11.0, "#f2d43d"),
    (13.0, "#f5a142"),
    (15.0, "#e8603c"),
    (18.0, "#c2304f"),
    (21.0, "#8e3a8f"),
]


def wind_colour(speed_ms: Optional[float]) -> str:
    if speed_ms is None:
        return "#eeeeee"
    colour = WIND_COLOURS[0][1]
    for lower, c in WIND_COLOURS:
        if speed_ms >= lower:
            colour = c
    return colour


def _hourly(forecast: Sequence[ForecastPoint], max_columns: int) -> list[ForecastPoint]:
    """Full-hour forecast points only, so the table reads like Windy's."""
    points = [p for p in forecast if p.timestamp.minute == 0] or list(forecast)
    return points[:max_columns]


def _model_row(points: Sequence[ForecastPoint], timestamps: list) -> list[Optional[ForecastPoint]]:
    """Align a comparison model's points to the FMI table's columns."""
    by_time = {p.timestamp: p for p in points}
    return [by_time.get(ts) for ts in timestamps]


def _draw_forecast_table(
    ax,
    forecast: Sequence[ForecastPoint],
    wind_cfg: Optional[WindConfig],
    model_forecasts: Optional[dict[str, Sequence[ForecastPoint]]] = None,
) -> int:
    """Hourly table: time, wind + gust in coloured cells, one row per
    comparison model, direction arrow. Returns the number of rows drawn."""
    model_rows = [
        (model_label(m), _model_row(pts, [p.timestamp for p in forecast]))
        for m, pts in (model_forecasts or {}).items()
    ]
    rows = ["Klo", "Tuuli", "Puuska"] + [label for label, _ in model_rows] + ["Suunta"]
    if wind_cfg is not None:
        rows.append("Sopiva")
    dir_row = rows.index("Suunta")
    n_rows = len(rows)

    ax.set_xlim(-1.4, len(forecast))
    ax.set_ylim(n_rows, 0)
    ax.axis("off")

    for r, label in enumerate(rows):
        ax.text(-0.1, r + 0.5, label, ha="right", va="center", fontsize=8, color="#444444")

    def cell(c: int, r: int, value: Optional[float], gust: Optional[float] = None) -> None:
        ax.add_patch(plt.Rectangle((c + 0.03, r + 0.05), 0.94, 0.9, color=wind_colour(value)))
        text = "-" if value is None else f"{value:.0f}"
        if gust is None:
            ax.text(c + 0.5, r + 0.5, text, ha="center", va="center", fontsize=10, weight="bold")
        else:
            ax.text(c + 0.5, r + 0.4, text, ha="center", va="center", fontsize=10, weight="bold")
            ax.text(c + 0.5, r + 0.8, f"({gust:.0f})", ha="center", va="center", fontsize=6)

    for c, p in enumerate(forecast):
        local = p.timestamp.astimezone(LOCAL_TZ)
        ax.text(c + 0.5, 0.5, local.strftime("%H"), ha="center", va="center", fontsize=9, weight="bold")

        cell(c, 1, p.speed_ms)
        cell(c, 2, p.gust_ms)
        for i, (_, points) in enumerate(model_rows):
            mp = points[c]
            cell(c, 3 + i, mp.speed_ms if mp else None, mp.gust_ms if mp else None)

        if p.direction_deg is not None:
            # Arrow points where the wind blows to, as on Windy.
            to_rad = math.radians(p.direction_deg + 180)
            dx, dy = 0.3 * math.sin(to_rad), -0.3 * math.cos(to_rad)  # y axis is inverted
            y = dir_row + 0.4
            ax.annotate(
                "", xy=(c + 0.5 + dx, y + dy), xytext=(c + 0.5 - dx, y - dy),
                arrowprops=dict(arrowstyle="-|>", color="#333333", lw=1.5),
            )
            ax.text(c + 0.5, dir_row + 0.88, deg_to_compass(p.direction_deg), ha="center", va="center", fontsize=6)

        if wind_cfg is not None and p.speed_ms is not None:
            ok = wind_cfg.min_speed_ms <= p.speed_ms <= wind_cfg.max_speed_ms
            ax.add_patch(plt.Rectangle(
                (c + 0.03, dir_row + 1.3), 0.94, 0.4, color="#2e9e44" if ok else "#dddddd",
            ))
    return n_rows


def generate_wind_chart(
    observations: Sequence[WindReading],
    forecast: Sequence[ForecastPoint],
    output_path: str,
    wind_cfg: Optional[WindConfig] = None,
    title: str = "Tuuli",
    table_hours: int = 0,
    model_forecasts: Optional[dict[str, Sequence[ForecastPoint]]] = None,
) -> str:
    """Render a PNG chart of observed + forecast wind speed/gust over time,
    optionally with a Windy-style hourly forecast table underneath.
    Returns the output_path for convenience (so callers can chain it
    straight into Alert.image_path)."""
    table_points = _hourly([p for p in forecast if p.speed_ms is not None], table_hours)
    model_forecasts = model_forecasts or {}
    if table_points:
        table_height = 2.2 + 0.45 * len(model_forecasts)
        fig, (ax, table_ax) = plt.subplots(
            2, 1, figsize=(8, 4 + table_height), gridspec_kw={"height_ratios": [4, table_height]},
        )
    else:
        fig, ax = plt.subplots(figsize=(8, 4))
        table_ax = None

    valid_obs = [o for o in observations if o.speed_ms is not None]
    if valid_obs:
        ax.plot(
            [o.timestamp for o in valid_obs],
            [o.speed_ms for o in valid_obs],
            label="Tuuli (havaittu)",
            color="#1f77b4",
            linewidth=2,
        )
        gust_obs = [o for o in valid_obs if o.gust_ms is not None]
        if gust_obs:
            ax.plot(
                [o.timestamp for o in gust_obs],
                [o.gust_ms for o in gust_obs],
                label="Puuska (havaittu)",
                color="#1f77b4",
                alpha=0.4,
                linestyle="--",
            )

    valid_forecast = [p for p in forecast if p.speed_ms is not None]
    if valid_forecast:
        ax.plot(
            [p.timestamp for p in valid_forecast],
            [p.speed_ms for p in valid_forecast],
            label="Tuuli (ennuste)",
            color="#ff7f0e",
            linestyle=":",
            linewidth=2,
        )
        gust_forecast = [p for p in valid_forecast if p.gust_ms is not None]
        if gust_forecast:
            ax.plot(
                [p.timestamp for p in gust_forecast],
                [p.gust_ms for p in gust_forecast],
                label="Puuska (ennuste)",
                color="#ff7f0e",
                alpha=0.4,
                linestyle="-.",
            )

    model_colours = ["#2ca02c", "#9467bd", "#8c564b"]
    for i, (model, points) in enumerate(model_forecasts.items()):
        valid = [p for p in points if p.speed_ms is not None]
        if valid:
            ax.plot(
                [p.timestamp for p in valid],
                [p.speed_ms for p in valid],
                label=f"Tuuli ({model_label(model)})",
                color=model_colours[i % len(model_colours)],
                linewidth=1.2,
                alpha=0.8,
            )

    if wind_cfg is not None:
        ax.axhline(wind_cfg.min_speed_ms, color="green", linestyle="--", alpha=0.5, label="Alaraja")
        ax.axhline(wind_cfg.max_speed_ms, color="red", linestyle="--", alpha=0.5, label="Yläraja")

    ax.set_ylabel("m/s")
    ax.set_title(title)
    if ax.get_legend_handles_labels()[0]:
        ax.legend(fontsize=8, loc="upper left")
    ax.grid(alpha=0.2)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=LOCAL_TZ))
    if table_ax is not None:
        _draw_forecast_table(table_ax, table_points, wind_cfg, model_forecasts)
        table_ax.set_title("Ennuste tunneittain (m/s), Tuuli/Puuska = FMI", fontsize=9, loc="left")
    if model_forecasts:
        fig.text(0.99, 0.005, ATTRIBUTION, ha="right", va="bottom", fontsize=6, color="#777777")
    else:
        fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(output_path, dpi=120)
    plt.close(fig)
    return output_path
