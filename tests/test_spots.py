import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.config import ConfigError, SpotConfig, load_config  # noqa: E402
from core.spots import recommend_spots, spots_summary  # noqa: E402

KAUPINOJA = SpotConfig(
    name="Kaupinojanlahti", direction_ranges=[(300, 350), (10, 60)],
    url="https://surffikamu.fi/spot/2",
)
KOUKKUNIEMI = SpotConfig(name="Koukkuniemi", direction_ranges=[(325, 15)])
RAHOLA = SpotConfig(name="Rahola", direction_ranges=[(100, 125), (165, 240)], favorite=True)


def names(matches):
    return [m.spot.name for m in matches]


def test_direction_inside_range_matches():
    assert names(recommend_spots([KAUPINOJA, RAHOLA], 200)) == ["Rahola"]


def test_range_wrapping_over_north():
    assert names(recommend_spots([KOUKKUNIEMI], 5)) == ["Koukkuniemi"]
    assert names(recommend_spots([KOUKKUNIEMI], 340)) == ["Koukkuniemi"]
    assert recommend_spots([KOUKKUNIEMI], 30) == []


def test_mid_range_beats_edge():
    # 340 is mid-range for Koukkuniemi (325-15) but near the edge of 300-350.
    assert names(recommend_spots([KAUPINOJA, KOUKKUNIEMI], 345)) == ["Koukkuniemi", "Kaupinojanlahti"]


def test_favorite_ranks_first():
    fav = SpotConfig(name="Suosikki", direction_ranges=[(300, 350)], favorite=True)
    assert names(recommend_spots([KOUKKUNIEMI, fav], 345))[0] == "Suosikki"


def test_favorites_only_filters_others():
    assert recommend_spots([KAUPINOJA], 320, favorites_only=True) == []


def test_missing_direction_gives_no_recommendations():
    assert recommend_spots([KAUPINOJA], None) == []
    assert spots_summary([KAUPINOJA], None) is None


def test_summary_lists_links_and_respects_limit():
    text = spots_summary([KAUPINOJA, KOUKKUNIEMI], 340, max_listed=1)
    assert "Koukkuniemi" in text
    assert "Kaupinojanlahti" not in text
    text = spots_summary([KAUPINOJA], 325)
    assert "https://surffikamu.fi/spot/2" in text


def test_summary_when_nothing_matches():
    assert "ei löytynyt" in spots_summary([KAUPINOJA], 200)


SPOTS_CONFIG = """
location: {name: "T", latitude: 61.5, longitude: 23.7}
notifications:
  channels:
    - {type: ntfy, enabled: true, topic: "x"}
spots:
  enabled: true
  list:
    - name: "Kaupinojanlahti"
      url: "https://surffikamu.fi/spot/2"
      directions: ["300-350", "10-60°"]
      favorite: true
"""


def write_temp_config(text):
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8")
    f.write(text)
    f.close()
    return f.name


def test_config_parses_spots():
    cfg = load_config(write_temp_config(SPOTS_CONFIG))
    assert cfg.spots.enabled
    spot = cfg.spots.spots[0]
    assert spot.direction_ranges == [(300.0, 350.0), (10.0, 60.0)]
    assert spot.favorite


def test_config_rejects_bad_range():
    with pytest.raises(ConfigError):
        load_config(write_temp_config(SPOTS_CONFIG.replace('"300-350"', '"luode"')))
