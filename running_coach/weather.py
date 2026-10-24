"""Weather for the runner's home location.

Open-Meteo (free, no API key) for both geocoding and forecast. Two surfaces:

  geocode(query)        -> resolve free-text "City, country" to lat/lon + display.
  current_weather(conn) -> read the saved home location, fetch today's forecast,
                            day-cache it, return a small dict for the dashboard
                            + LLM context.

All network calls have a 5s timeout and fail soft (return None). The dashboard
and the LLM context layer both render gracefully when this returns None — no
weather just means no chip.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from typing import Any

from . import settings as app_settings

log = logging.getLogger(__name__)

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

HTTP_TIMEOUT_S = 5

# WMO weather codes → short human description. Keys not listed render as "—".
# See https://open-meteo.com/en/docs (Weather variable documentation).
WEATHER_CODES: dict[int, str] = {
    0: "Clear",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Heavy drizzle",
    56: "Freezing drizzle",
    57: "Freezing drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    66: "Freezing rain",
    67: "Freezing rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Rain showers",
    81: "Rain showers",
    82: "Heavy rain showers",
    85: "Snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm w/ hail",
    99: "Thunderstorm w/ hail",
}


def describe_code(code: int | None) -> str:
    if code is None:
        return "—"
    return WEATHER_CODES.get(int(code), "—")


# WMO code → emoji icon. Day/night variants for clear & mainly-clear codes.
_ICONS_DAY: dict[int, str] = {
    0: "☀",  1: "🌤",  2: "⛅",  3: "☁",
    45: "🌫", 48: "🌫",
    51: "🌦", 53: "🌦", 55: "🌧",
    56: "🌧", 57: "🌧",
    61: "🌧", 63: "🌧", 65: "🌧",
    66: "🌧", 67: "🌧",
    71: "🌨", 73: "🌨", 75: "❄",
    77: "❄",
    80: "🌦", 81: "🌧", 82: "🌧",
    85: "🌨", 86: "❄",
    95: "⛈", 96: "⛈", 99: "⛈",
}
_ICONS_NIGHT: dict[int, str] = {**_ICONS_DAY, 0: "🌙", 1: "🌙", 2: "☁"}


def icon_for_code(code: int | None, is_day: bool | None = True) -> str:
    if code is None:
        return "·"
    table = _ICONS_DAY if (is_day is None or is_day) else _ICONS_NIGHT
    return table.get(int(code), "·")


def _fetch_json(url: str, params: dict[str, Any]) -> dict | None:
    query = urllib.parse.urlencode(params, doseq=True)
    full_url = f"{url}?{query}"
    try:
        with urllib.request.urlopen(full_url, timeout=HTTP_TIMEOUT_S) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — fail soft on any network/parse issue
        log.warning("weather fetch failed: %s (url=%s)", exc, url)
        return None


def _geocode_one(query: str) -> dict | None:
    data = _fetch_json(GEOCODE_URL, {"name": query, "count": 1, "language": "en"})
    if not data or not data.get("results"):
        return None
    return data["results"][0]


def geocode(query: str) -> dict[str, Any] | None:
    """Resolve a free-text query (e.g. "Wassenaar" or "Wassenaar, Netherlands")
    to a location dict.

    Open-Meteo's geocoder accepts a single place name (no commas). We try the
    full string first; if that returns no results, we fall back to the first
    comma-separated part. Returns {lat, lon, display_name, country_code} or
    None on failure / no match.
    """
    query = (query or "").strip()
    if not query:
        return None

    first = _geocode_one(query)
    if first is None and "," in query:
        # Retry with just the leading part — Open-Meteo doesn't accept "City, Country".
        head = query.split(",", 1)[0].strip()
        if head:
            first = _geocode_one(head)

    if first is None:
        return None

    # Build a human-readable display name. Open-Meteo returns name, admin1, country.
    parts = [first.get("name"), first.get("admin1"), first.get("country")]
    display = ", ".join(p for p in parts if p)
    return {
        "lat": float(first["latitude"]),
        "lon": float(first["longitude"]),
        "display_name": display,
        "country_code": first.get("country_code"),
    }


def _cache_key(lat: float, lon: float, today: date) -> str:
    # 2-decimal lat/lon is ~1km precision — plenty for a daily forecast, and stable
    # against the geocoder returning slightly different coords on re-save.
    return f"forecast:{lat:.2f}:{lon:.2f}:{today.isoformat()}"


def _read_cache(conn: sqlite3.Connection, key: str) -> dict | None:
    row = conn.execute(
        "SELECT payload FROM weather_cache WHERE cache_key = ?", (key,)
    ).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["payload"])
    except Exception:  # noqa: BLE001
        return None


def _write_cache(conn: sqlite3.Connection, key: str, payload: dict) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO weather_cache (cache_key, payload, fetched_at)
           VALUES (?, ?, datetime('now'))""",
        (key, json.dumps(payload)),
    )
    conn.commit()


def _score_hour(
    temp_c: float | None,
    precip_prob_pct: float | None,
    wind_kmh: float | None,
    is_day: bool | None,
) -> float:
    """Heuristic runnability score 0–100 for a single hour. Higher is better.

    Sweet spot: 5–18°C, dry, light wind, daylight. Tuned for amateur road runners.
    """
    score = 100.0

    if temp_c is not None:
        if temp_c > 25:
            score -= (temp_c - 25) * 5
        elif temp_c > 18:
            score -= (temp_c - 18) * 2
        elif temp_c < 0:
            score -= (0 - temp_c) * 5
        elif temp_c < 5:
            score -= (5 - temp_c) * 2

    if precip_prob_pct is not None:
        # Linear penalty from 0 — drier hours always rank higher than wetter
        # hours of identical temp/wind. Above 30% the slope steepens.
        score -= precip_prob_pct * 0.3
        if precip_prob_pct > 30:
            score -= (precip_prob_pct - 30) * 0.7

    if wind_kmh is not None and wind_kmh > 20:
        score -= (wind_kmh - 20)

    if is_day is False:
        score -= 25

    return max(0.0, score)


def _best_window(
    hourly: dict,
    today: date,
    *,
    window_hours: int = 2,
    now: datetime | None = None,
) -> dict | None:
    """Find the highest-scoring contiguous `window_hours`-block among today's
    remaining hours. Returns None if fewer than `window_hours` future hours
    remain today. Open-Meteo times are local to the location (timezone=auto in
    the fetch call); we compare against the server's local `datetime.now()`."""
    times = hourly.get("time") or []
    if not times:
        return None
    now = now or datetime.now()

    temps  = hourly.get("temperature_2m") or []
    precip = hourly.get("precipitation_probability") or []
    winds  = hourly.get("wind_speed_10m") or []
    codes  = hourly.get("weather_code") or []
    days   = hourly.get("is_day") or []

    candidates: list[dict] = []
    for i, t in enumerate(times):
        try:
            dt = datetime.fromisoformat(t)
        except (TypeError, ValueError):
            continue
        if dt.date() != today:
            continue
        # Skip already-past hours (with a 30-min grace so the chip doesn't lose
        # "now" the moment the clock ticks).
        if dt < now - timedelta(minutes=30):
            continue
        candidates.append({
            "dt":          dt,
            "temp_c":      temps[i]  if i < len(temps)  else None,
            "precip_prob": precip[i] if i < len(precip) else None,
            "wind_kmh":    winds[i]  if i < len(winds)  else None,
            "weather_code":codes[i]  if i < len(codes)  else None,
            "is_day":      bool(days[i]) if i < len(days) else None,
        })

    if len(candidates) < window_hours:
        return None

    best: dict | None = None
    for i in range(len(candidates) - window_hours + 1):
        win = candidates[i : i + window_hours]
        avg_score = sum(
            _score_hour(h["temp_c"], h["precip_prob"], h["wind_kmh"], h["is_day"])
            for h in win
        ) / window_hours
        if best is None or avg_score > best["score"]:
            temps_present = [h["temp_c"] for h in win if h["temp_c"] is not None]
            winds_present = [h["wind_kmh"] for h in win if h["wind_kmh"] is not None]
            best = {
                "start":         win[0]["dt"].strftime("%H:%M"),
                "end":           (win[-1]["dt"] + timedelta(hours=1)).strftime("%H:%M"),
                "score":         round(avg_score),
                "avg_temp_c":    sum(temps_present) / len(temps_present) if temps_present else None,
                "max_precip_pct":max((h["precip_prob"] or 0) for h in win),
                "avg_wind_kmh":  sum(winds_present) / len(winds_present) if winds_present else None,
                "weather_text":  describe_code(win[len(win) // 2]["weather_code"]),
            }
    return best


def hourly_breakdown(weather: dict, *, today: date | None = None) -> list[dict]:
    """Render-ready list of dicts, one per hour of the forecast horizon.

    Pulls the raw `hourly` arrays out of a cached `current_weather()` payload
    and decorates each hour with display fields the modal template needs:
    icon, score, day-boundary flag, sunrise/sunset markers, best-window
    membership.
    """
    today = today or date.today()
    hourly = weather.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        return []

    temps  = hourly.get("temperature_2m") or []
    precip = hourly.get("precipitation_probability") or []
    winds  = hourly.get("wind_speed_10m") or []
    codes  = hourly.get("weather_code") or []
    days   = hourly.get("is_day") or []

    # Best window: list of formatted "HH:MM" strings on today's date that fall
    # in [start, end). Tomorrow's hours never sit in a "today" window.
    bw = weather.get("best_window") or {}
    bw_today_only = bool(bw)
    bw_start = bw.get("start")  # e.g. "20:00"
    bw_end   = bw.get("end")    # e.g. "22:00"

    # Sunrise / sunset markers per day. Open-Meteo daily arrays are indexed by
    # day (index 0 = today, index 1 = tomorrow). The value is ISO local time;
    # we floor it to the hour and use it as a set membership test.
    def _floor_to_hour(iso: str | None) -> str | None:
        if not iso:
            return None
        try:
            dt = datetime.fromisoformat(iso)
            return dt.replace(minute=0, second=0, microsecond=0).isoformat()
        except (TypeError, ValueError):
            return None

    sunrise_hours: set[str] = set()
    sunset_hours: set[str] = set()
    # The normalized cache stores only today's sunrise/sunset (sunrise/sunset
    # are scalars on the top-level dict, not the full daily array). That's
    # enough for the "today" column markers; tomorrow's marker is future work.
    sr = _floor_to_hour(weather.get("sunrise"))
    ss = _floor_to_hour(weather.get("sunset"))
    if sr:
        sunrise_hours.add(sr)
    if ss:
        sunset_hours.add(ss)

    seen_dates: set[str] = set()
    out: list[dict] = []
    for i, t in enumerate(times):
        try:
            dt = datetime.fromisoformat(t)
        except (TypeError, ValueError):
            continue
        d_iso = dt.date().isoformat()
        is_first = d_iso not in seen_dates
        if is_first:
            seen_dates.add(d_iso)
            if dt.date() == today:
                day_label = "Today"
            elif dt.date() == today + timedelta(days=1):
                day_label = "Tomorrow"
            else:
                day_label = dt.strftime("%a %d %b")
        else:
            day_label = None

        temp_c     = temps[i]  if i < len(temps)  else None
        prc        = precip[i] if i < len(precip) else None
        wind       = winds[i]  if i < len(winds)  else None
        code       = codes[i]  if i < len(codes)  else None
        is_day_h   = bool(days[i]) if i < len(days) else True
        score      = round(_score_hour(temp_c, prc, wind, is_day_h))
        time_short = dt.strftime("%H:%M")
        in_bw = (
            bw_today_only
            and dt.date() == today
            and bw_start is not None
            and bw_end is not None
            and bw_start <= time_short < bw_end
        )
        floor_iso = dt.replace(minute=0, second=0, microsecond=0).isoformat()
        out.append({
            "dt": t,
            "date": d_iso,
            "time_short": time_short,
            "is_first_of_day": is_first,
            "day_label": day_label,
            "temp_c": temp_c,
            "weather_code": code,
            "weather_text": describe_code(code),
            "icon": icon_for_code(code, is_day_h),
            "precip_prob_pct": prc,
            "wind_kmh": wind,
            "is_day": is_day_h,
            "score": score,
            "in_best_window": in_bw,
            "is_sunrise": floor_iso in sunrise_hours,
            "is_sunset":  floor_iso in sunset_hours,
        })
    return out


def fetch_current(lat: float, lon: float) -> dict | None:
    """Fetch only the `current=` block from Open-Meteo. Used to refresh the
    live readings (temp, conditions, wind) on every dashboard load without
    re-pulling the day-cached hourly + daily arrays.

    Returns a small dict with `current_temp_c`, `feels_like_c`, `wind_kmh`,
    `wind_dir_deg`, `weather_code`, `weather_text`, or None on network
    failure. Callers should fail soft on None and keep showing whatever
    the cache last had.
    """
    params = {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,wind_direction_10m",
        "timezone": "auto",
        "wind_speed_unit": "kmh",
    }
    data = _fetch_json(FORECAST_URL, params)
    if not data:
        return None
    current = data.get("current") or {}
    return {
        "current_temp_c": current.get("temperature_2m"),
        "feels_like_c":   current.get("apparent_temperature"),
        "wind_kmh":       current.get("wind_speed_10m"),
        "wind_dir_deg":   current.get("wind_direction_10m"),
        "weather_code":   current.get("weather_code"),
        "weather_text":   describe_code(current.get("weather_code")),
    }


def fetch_forecast(lat: float, lon: float, today: date | None = None) -> dict | None:
    """Fetch raw forecast from Open-Meteo (no cache). Returns a small normalized
    dict, or None on network failure."""
    today = today or date.today()
    params = {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,wind_direction_10m",
        "hourly": "temperature_2m,weather_code,precipitation_probability,wind_speed_10m,is_day",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code,sunrise,sunset",
        "timezone": "auto",
        "forecast_days": 2,
        "wind_speed_unit": "kmh",
    }
    data = _fetch_json(FORECAST_URL, params)
    if not data:
        return None

    current = data.get("current") or {}
    daily = data.get("daily") or {}
    hourly = data.get("hourly") or {}
    # Open-Meteo's daily fields are parallel arrays indexed by day. Index 0 is today.
    def _d(key: str, i: int = 0):
        vals = daily.get(key) or []
        return vals[i] if len(vals) > i else None

    return {
        "current_temp_c":    current.get("temperature_2m"),
        "feels_like_c":      current.get("apparent_temperature"),
        "wind_kmh":          current.get("wind_speed_10m"),
        "wind_dir_deg":      current.get("wind_direction_10m"),
        "weather_code":      current.get("weather_code"),
        "weather_text":      describe_code(current.get("weather_code")),
        "high_c":            _d("temperature_2m_max"),
        "low_c":             _d("temperature_2m_min"),
        "precip_prob_pct":   _d("precipitation_probability_max"),
        "daily_code":        _d("weather_code"),
        "daily_text":        describe_code(_d("weather_code")),
        "sunrise":           _d("sunrise"),
        "sunset":            _d("sunset"),
        # Raw hourly arrays kept so best_window can recompute on each read —
        # without this the cached "best window" would drift into the past as
        # the day progresses.
        "hourly":            hourly,
        "fetched_for_date":  today.isoformat(),
    }


def current_weather(
    conn: sqlite3.Connection,
    *,
    force_refresh: bool = False,
) -> dict | None:
    """Read the saved home location, return today's cached forecast (fetching if
    needed). None when no location is set, or the network fails on first fetch."""
    loc = app_settings.get_home_location(conn)
    if not loc or loc["lat"] is None or loc["lon"] is None:
        return None

    today = date.today()
    key = _cache_key(loc["lat"], loc["lon"], today)

    payload: dict | None = None
    just_fetched = False
    if not force_refresh:
        payload = _read_cache(conn, key)

    if payload is None:
        payload = fetch_forecast(loc["lat"], loc["lon"], today)
        if not payload:
            return None
        just_fetched = True
        # Annotate with the saved location so the dashboard chip can display it
        # without a separate query. Stored in the cache so subsequent reads have it.
        payload["display_name"] = loc["display_name"]
        payload["country_code"] = loc.get("country_code")
        try:
            _write_cache(conn, key, payload)
        except Exception:  # noqa: BLE001 — caching is best-effort
            log.exception("weather cache write failed")

    # Refresh the live "current" readings (temp, conditions, wind) on every
    # cache-hit read so the dashboard chip shows what's outside *now*, not
    # what it was when the day's cache entry was first written. Skipped on a
    # cache-miss path where the full forecast we just fetched already carries
    # the live current values. Falls back silently to the cached values if
    # the network call fails — chip stays useful.
    if not just_fetched:
        fresh = fetch_current(loc["lat"], loc["lon"])
        if fresh:
            # Don't persist these into the day-cache — keep that as the
            # "first fetch of the day" snapshot. Overlay only on the
            # returned dict.
            payload = {**payload, **fresh}

    # best_window is recomputed on every read so it advances through the day
    # even when the rest of the forecast is served from the cache.
    payload["best_window"] = _best_window(payload.get("hourly") or {}, today)
    return payload
