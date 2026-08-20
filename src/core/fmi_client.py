"""Client for the Finnish Meteorological Institute's open data WFS API.

Two stored queries are used:
- fmi::observations::weather::timevaluepair   -> recent real observations
- fmi::forecast::harmonie::surface::point::timevaluepair -> forecast

Both return WFS/GML XML with <wml2:MeasurementTimeseries> blocks per
parameter. We parse just enough of that to get (timestamp, value) pairs.

Robustness notes:
- Every network call goes through `_get_with_retry`, which retries with
  exponential backoff. FMI's API is free and occasionally slow/flaky -
  a single fetch failure must not be treated the same as "no wind".
- Station lookup: if the user hasn't set fmi_station_id, we look up
  the nearest observation station from FMI's station list and fall back
  to a small embedded list of well-known coastal/lake stations if that
  lookup itself fails (e.g. FMI API temporarily down).
"""
from __future__ import annotations

import logging
import math
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from .models import ForecastPoint, WindReading

log = logging.getLogger(__name__)

FMI_WFS_URL = "https://opendata.fmi.fi/wfs"

_NS = {
    "wfs": "http://www.opengis.net/wfs/2.0",
    "gml": "http://www.opengis.net/gml/3.2",
    "wml2": "http://www.opengis.net/waterml/2.0",
    "om": "http://www.opengis.net/om/2.0",
    "target": "http://xml.fmi.fi/namespace/om/atmosphericfeatures/1.1",
}

# Small embedded fallback list (fmisid, name, lat, lon) of stations that are
# useful for water sports around Finland's coast and larger lakes. Used only
# if the live FMI station-list query fails. Not exhaustive by design - the
# live lookup is always tried first.
FALLBACK_STATIONS = [
    (100996, "Helsinki Kaisaniemi", 60.1749, 24.9439),
    (101023, "Helsinki Harmaja", 60.1049, 24.9754),
    (101267, "Turku lentoasema", 60.5141, 22.2628),
    (101118, "Hanko Tulliniemi", 59.8154, 22.8926),
    (101673, "Kotka Rankki", 60.2967, 26.9642),
    (101784, "Lappeenranta lentoasema", 61.0447, 28.1447),
    (101339, "Rauma Kylmäpihlaja", 61.1400, 21.3200),
    (101586, "Vaasa lentoasema", 63.0503, 21.7692),
    (101673, "Oulu lentoasema", 64.9300, 25.3544),
    (101311, "Jyväskylä lentoasema", 62.3986, 25.6786),
]

_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class FmiApiError(RuntimeError):
    """Raised when FMI data cannot be fetched or parsed after retries."""


def _get_with_retry(params: dict, attempts: int = 3, base_delay: float = 5.0) -> str:
    last_exc: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        try:
            resp = requests.get(FMI_WFS_URL, params=params, timeout=20)
            if resp.status_code in _RETRYABLE_STATUSES:
                raise FmiApiError(f"FMI returned HTTP {resp.status_code}")
            resp.raise_for_status()
            if not resp.text or "<" not in resp.text:
                raise FmiApiError("FMI returned an empty/non-XML response")
            return resp.text
        except (requests.RequestException, FmiApiError) as e:
            last_exc = e
            log.warning("FMI request failed (attempt %d/%d): %s", attempt, attempts, e)
            if attempt < attempts:
                time.sleep(base_delay * (2 ** (attempt - 1)))
    raise FmiApiError(f"FMI request failed after {attempts} attempts: {last_exc}")


def _parse_timeseries(xml_text: str) -> dict[str, list[tuple[datetime, Optional[float]]]]:
    """Parse all MeasurementTimeseries blocks into {parameter_name: [(ts, value), ...]}."""
    root = ET.fromstring(xml_text)
    result: dict[str, list[tuple[datetime, Optional[float]]]] = {}

    for ts_elem in root.iter(f"{{{_NS['wml2']}}}MeasurementTimeseries"):
        gml_id = ts_elem.get(f"{{{_NS['gml']}}}id", "")
        # gml:id looks like "mts-1-1-ws_10min" - parameter name is the suffix.
        param_name = gml_id.split("-")[-1] if gml_id else "unknown"

        points = []
        for point in ts_elem.iter(f"{{{_NS['wml2']}}}MeasurementTVP"):
            time_el = point.find(f"{{{_NS['wml2']}}}time")
            value_el = point.find(f"{{{_NS['wml2']}}}value")
            if time_el is None or time_el.text is None:
                continue
            ts = datetime.fromisoformat(time_el.text.replace("Z", "+00:00"))
            value: Optional[float] = None
            if value_el is not None and value_el.text and value_el.text.upper() != "NAN":
                try:
                    value = float(value_el.text)
                except ValueError:
                    value = None
            points.append((ts, value))

        result[param_name] = points

    return result


def find_nearest_station(latitude: float, longitude: float) -> tuple[int, str]:
    """Return (fmisid, name) of the nearest observation station.

    Tries FMI's live station list first; falls back to an embedded list of
    well-known stations if the live query fails for any reason.
    """
    try:
        xml_text = _get_with_retry(
            {
                "service": "WFS",
                "version": "2.0.0",
                "request": "getFeature",
                "storedquery_id": "fmi::ef::stations",
                "networkid": "121",  # weather observation network
            },
            attempts=2,
        )
        root = ET.fromstring(xml_text)
        candidates = []
        for member in root:
            pos_el = member.find(".//{http://www.opengis.net/gml/3.2}pos")
            id_el = member.find(".//{http://xml.fmi.fi/schema/wfs/2.0}fmisid")
            name_el = member.find(".//{http://xml.fmi.fi/schema/wfs/2.0}name")
            if pos_el is None or id_el is None or not pos_el.text:
                continue
            lat_s, lon_s = pos_el.text.split()
            candidates.append(
                (int(id_el.text), name_el.text if name_el is not None else "?",
                 float(lat_s), float(lon_s))
            )
        if not candidates:
            raise FmiApiError("Station list query returned no stations")
    except Exception as e:  # noqa: BLE001 - deliberately broad, has a fallback
        log.warning("Live station lookup failed, using fallback list: %s", e)
        candidates = FALLBACK_STATIONS

    def dist(c):
        return (c[2] - latitude) ** 2 + (c[3] - longitude) ** 2

    nearest = min(candidates, key=dist)
    return nearest[0], nearest[1]


def fetch_observations(fmisid: int, lookback_minutes: int = 60) -> list[WindReading]:
    """Fetch recent wind observations (10-min resolution) for a station."""
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=lookback_minutes)

    xml_text = _get_with_retry(
        {
            "service": "WFS",
            "version": "2.0.0",
            "request": "getFeature",
            "storedquery_id": "fmi::observations::weather::timevaluepair",
            "fmisid": str(fmisid),
            "parameters": "ws_10min,wg_10min,wd_10min",
            "starttime": start_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "endtime": end_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    )
    series = _parse_timeseries(xml_text)
    return _merge_series_to_readings(series, "ws_10min", "wg_10min", "wd_10min", WindReading)


def fetch_forecast(latitude: float, longitude: float, hours_ahead: int = 6) -> list[ForecastPoint]:
    """Fetch HARMONIE forecast points for the given hours ahead."""
    end_time = datetime.now(timezone.utc) + timedelta(hours=hours_ahead)

    xml_text = _get_with_retry(
        {
            "service": "WFS",
            "version": "2.0.0",
            "request": "getFeature",
            "storedquery_id": "fmi::forecast::harmonie::surface::point::timevaluepair",
            "latlon": f"{latitude},{longitude}",
            "parameters": "WindSpeedMS,WindGust,WindDirection",
            "endtime": end_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    )
    series = _parse_timeseries(xml_text)
    return _merge_series_to_readings(
        series, "WindSpeedMS", "WindGust", "WindDirection", ForecastPoint
    )


def _merge_series_to_readings(series, speed_key, gust_key, dir_key, cls):
    speed_points = {ts: v for ts, v in series.get(speed_key, [])}
    gust_points = {ts: v for ts, v in series.get(gust_key, [])}
    dir_points = {ts: v for ts, v in series.get(dir_key, [])}

    all_ts = sorted(set(speed_points) | set(gust_points) | set(dir_points))
    readings = []
    for ts in all_ts:
        readings.append(
            cls(
                timestamp=ts,
                speed_ms=speed_points.get(ts),
                gust_ms=gust_points.get(ts),
                direction_deg=dir_points.get(ts),
            )
        )
    return readings
