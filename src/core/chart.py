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

from typing import Optional, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .config import WindConfig  # noqa: E402
from .models import ForecastPoint, WindReading  # noqa: E402


def generate_wind_chart(
    observations: Sequence[WindReading],
    forecast: Sequence[ForecastPoint],
    output_path: str,
    wind_cfg: Optional[WindConfig] = None,
    title: str = "Tuuli",
) -> str:
    """Render a PNG chart of observed + forecast wind speed/gust over time.
    Returns the output_path for convenience (so callers can chain it
    straight into Alert.image_path)."""
    fig, ax = plt.subplots(figsize=(8, 4))

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

    if wind_cfg is not None:
        ax.axhline(wind_cfg.min_speed_ms, color="green", linestyle="--", alpha=0.5, label="Alaraja")
        ax.axhline(wind_cfg.max_speed_ms, color="red", linestyle="--", alpha=0.5, label="Yläraja")

    ax.set_ylabel("m/s")
    ax.set_title(title)
    if ax.get_legend_handles_labels()[0]:
        ax.legend(fontsize=8, loc="upper left")
    ax.grid(alpha=0.2)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(output_path, dpi=120)
    plt.close(fig)
    return output_path
