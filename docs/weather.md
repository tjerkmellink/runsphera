# Weather

> Today's forecast for the runner's home location, surfaced as a small chip on the dashboard and fed into the LLM coach so the daily banner can react to conditions. Open-Meteo (free, no API key) for both geocoding and forecast.

## Purpose

A coach who doesn't know it's 28°C and humid will tell you to crush your tempo at goal pace. Weather context lets the LLM coach adjust: "warm out — keep effort easy", "headwind on the long run, expect the pace to feel slower". The chip on the dashboard also doubles as a quick "should I run outside?" glance.

## How it works (user view)

### Settings → Location

Free-text "City, country" input on the Settings page. On save, Open-Meteo's geocoder resolves it to lat/lon plus a human-readable place name. The card flips to "● Set" with the resolved name, lat/lon, and country code visible. Wrong match? Type something more specific and re-save. The card has a Clear button for removing it.

### Dashboard weather chip

A small horizontal strip above today's-note editor (only renders when a location is set and the forecast was reachable):

```
12°C  partly cloudy   H 14° · L 6°   Wind 18 km/h   Rain 30%   Wassenaar, ...
─────────────────────────────────────────────────────────────────────────────
BEST WINDOW TODAY  17:00–19:00 · 14°C · partly cloudy · 10% rain
```

The **Best window** line picks the highest-scoring two-hour block among today's *remaining* hours, computed live on every dashboard load (the underlying hourly forecast is day-cached, but the window advances through the day). The headline **temperature, conditions text, and wind** also refresh on every page load (via an Open-Meteo `current=` call, ~1 KB) so they don't drift through the day. Falls silent if no location is set, or if the network call fails — the dashboard never breaks because of weather.

### 48-hour modal

Clicking the chip opens a modal with the next 48 hours laid out as horizontal columns:

- **One column per hour**: time, weather icon (☀ / 🌤 / ⛅ / ☁ / 🌧 / ❄ / ⛈ / 🌙), temperature, precipitation %, wind speed.
- **Score bar** down the right of each column — runnability 0–100 as a colored vertical fill (green → amber gradient).
- **Best-window columns** highlighted in green with a "BEST" tag overhead.
- **Day separator** between today and tomorrow — a dashed accent vertical with a "Tomorrow" label.
- **Sunrise / sunset markers** on the matching hour columns ("↑ sunrise", "↓ sunset").
- **Horizontal scroll** — columns are 60px wide, mobile-touchable, with subtle fade gradients on the left/right edges hinting at more content.

The modal uses the native `<dialog>` element (ESC and backdrop click both close).

### Coach voice

The LLM coach gets a `WEATHER TODAY` block in the per-request context. It picks up the conditions when relevant — e.g. on a hot day the banner might say "Heat's up — drop pace by 10–15s/km and run before the sun gets high." The persona is instructed to reference weather *only when it changes the right approach*, not as a daily filler.

## How it works (implementation)

### Modules

- [runsphera/weather.py](../runsphera/weather.py) — exported functions:
  - `geocode(query)` → resolve a free-text place to `{lat, lon, display_name, country_code}` or `None`. Falls back to the first comma-separated part when the full string doesn't resolve (Open-Meteo's geocoder doesn't accept "City, Country").
  - `fetch_forecast(lat, lon, today)` → raw Open-Meteo forecast call, returns a normalized dict including the raw `hourly` arrays.
  - `fetch_current(lat, lon)` → lightweight Open-Meteo `current=` call (temp, feels-like, wind, weather code). Used to refresh the live chip readings on every page load.
  - `current_weather(conn, *, force_refresh=False)` → cache-or-fetch entry point. Reads the saved home location, day-caches the heavy forecast, refreshes the live `current_*` fields and recomputes `best_window` on every read so they advance through the day.
  - `hourly_breakdown(weather)` → render-ready list of dicts, one per hour, with `time_short`, `icon`, `temp_c`, `precip_prob_pct`, `wind_kmh`, `score`, `in_best_window`, `is_sunrise`/`is_sunset`, `day_label` (set on first-of-day rows). Feeds the modal's column layout.
  - `icon_for_code(code, is_day)` → WMO weather code → emoji string. Day/night variants for clear & mainly-clear codes.
  - Plus `describe_code(code)` and internal `_score_hour` / `_best_window` helpers.

### Runnability scoring

Each future hour today gets a 0–100 score from `_score_hour`. Tuned for amateur road runners:

| Factor | Penalty |
|---|---|
| Temperature > 25°C | −5 per °C above 25 |
| Temperature > 18°C | −2 per °C above 18 |
| Temperature < 5°C | −2 per °C below 5 |
| Temperature < 0°C | −5 per °C below 0 |
| Precip prob > 30% | −1 per percentage point above 30 |
| Wind > 20 km/h | −1 per km/h above 20 |
| After sunset (`is_day = 0`) | −25 flat |

The "best window" picks the highest-scoring contiguous **two-hour** block among today's remaining hours (with a 30-min grace so the chip doesn't lose "now" the instant the clock ticks past). If fewer than two future hours remain today, no window is returned.

### Templates

- [_weather_chip.html](../runsphera/web/templates/_weather_chip.html) — the dashboard strip, rendered as a `<button>` that opens the modal.
- [_weather_modal.html](../runsphera/web/templates/_weather_modal.html) — the 48-h hourly columns dialog. Pre-rendered server-side; `<button onclick="document.getElementById('weather-modal').showModal()">` opens it client-side.
- [settings.html](../runsphera/web/templates/settings.html) — the Location card.

### Routes

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/settings/location` | Geocode the typed string and persist lat/lon + display. Invalidates today's `llm_cache`. Errors: `location_empty`, `location_unresolved`. |
| `POST` | `/settings/location/delete` | Clear the stored location. Invalidates today's `llm_cache`. Weather cache rows stay (they're keyed by lat/lon so they'll never be hit again). |
| `GET` | `/` | Calls `weather_service.current_weather(conn)` and passes the result to the dashboard template. |
| `GET` | `/settings` | Reads `home_location` into the Location card context. |

### DB

New columns on `app_settings` (single row, `id = 1`):

```
home_lat           REAL
home_lon           REAL
home_display_name  TEXT
home_country_code  TEXT
```

New table `weather_cache`:

```
cache_key   TEXT PRIMARY KEY    -- "forecast:{lat:.2f}:{lon:.2f}:{YYYY-MM-DD}"
payload     TEXT NOT NULL       -- JSON of the normalized forecast dict
fetched_at  TEXT NOT NULL       -- defaults to datetime('now')
```

Cache key uses 2-decimal lat/lon (~1 km precision) so it's stable against the geocoder returning slightly different coords on re-save.

### External service

Two Open-Meteo endpoints, both GET, both free, both no-API-key:

- **Geocoding**: `https://geocoding-api.open-meteo.com/v1/search?name=<query>&count=1&language=en`
- **Forecast**: `https://api.open-meteo.com/v1/forecast?latitude=...&longitude=...&current=...&hourly=...&daily=...&timezone=auto&forecast_days=2&wind_speed_unit=kmh`. Hourly fields fetched: `temperature_2m,weather_code,precipitation_probability,wind_speed_10m,is_day` — feeds the runnability scoring.

Both calls have a **5 s timeout** and **fail soft** — a network blip means no weather chip, not a broken dashboard.

### Data flow

```
User types "Wassenaar, Netherlands" → POST /settings/location
                                             ↓
                                weather.geocode()
                                             ↓ (Open-Meteo geocoding API)
                                {lat, lon, display, country_code}
                                             ↓
                                settings.set_home_location()  ──→ app_settings
                                             ↓
                                llm_commentary.invalidate_today()

User opens dashboard → GET / → weather.current_weather(conn)
                                             ↓
                              read weather_cache[key]
                            cached? ─yes─→ return
                                │ no
                                ↓
                              weather.fetch_forecast()
                                             ↓ (Open-Meteo forecast API)
                                  normalized forecast dict
                                             ↓
                              write weather_cache + return
                                             ↓
                          ┌──── dashboard chip
                          └──── LLM request_block → Claude
```

### Cache invalidation

- **Weather cache** keys are date+location. There's no explicit invalidation — the day rollover naturally evicts yesterday's entry.
- **LLM cache** invalidated on `POST /settings/location` (so the coach picks up new weather context) and `POST /settings/location/delete` (so it stops referencing now-absent weather).

## Configuration

| What | Where | Notes |
|---|---|---|
| Home location | `/settings` → Location card | Free-text input, geocoded once. Lat/lon stored. |
| Geocoder language | `weather.geocode` (`language=en`) | Hardcoded to English so resolved names match the rest of the UI. |
| Cache resolution | `_cache_key` (2-decimal lat/lon) | Trade between cache reuse and precision. |
| HTTP timeout | `HTTP_TIMEOUT_S = 5` | Short — we'd rather fail silent than slow the dashboard. |

## Known limitations

- **One location, no travel mode.** Saving a new location replaces the old. If you go training in another city for a week, you'd have to update Settings then change back. A "trip override" affordance is future work.
- **Geocoder picks the first match.** "Springfield" alone is ambiguous; the user needs to type "Springfield, MA" to disambiguate. Could add a multi-result picker in v2.
- **Daily granularity for the static headline numbers.** The chip's H/L and rain-probability are daily aggregates and cached for the whole day. Temperature, conditions, and wind refresh live on every page load; H/L stays static until tomorrow.
- **Server timezone vs location timezone.** Open-Meteo returns times in the location's local timezone (`timezone=auto`); we compare against the server's local `datetime.now()`. For a runner whose server and home location share a timezone (the common case for a local-first app), this is correct. Run the app from California against a Wassenaar location and the best-window math will be off by 9 hours.
- **No "feels like" surfaced.** The API returns `apparent_temperature`; we fetch it but don't render it on the chip. Worth adding when the temperature spread vs feels-like matters (humid summer days, windchill in winter).
- **No offline cache fallback.** A failed network call returns `None`; we don't fall back to yesterday's reading. Acceptable for now — fail-soft was the chosen tradeoff.

## Verification

1. **Geocode resolution.** Open `/settings`, type "Wassenaar, Netherlands" in the Location card, save. Banner says "Location saved." The card now shows "Resolved: Wassenaar, South Holland, Netherlands · Lat/Lon: 52.142, 4.401 · Country: NL".
2. **Geocode failure.** Type a string that won't resolve like "asdfasdf" and save. Card stays at "● Not set", red error banner says "Couldn't find that place."
3. **Dashboard chip.** Open `/`. The chip should appear above the Today's note editor showing temp + conditions + H/L + wind + precip prob + the location name on the right.
4. **No-location state.** Clear the location from Settings, refresh `/`. The chip should be absent (not "—" placeholder); the rest of the dashboard renders unchanged.
5. **Network failure.** Stop your network for a few seconds and refresh `/`. The chip should not render (graceful fail). The rest of the page loads in normal time.
6. **LLM context pickup.** With a Claude key configured and a location set, click the ↻ button on the coach banner. The regenerated message should reference today's weather *if it changes the approach* (e.g. on a rainy or hot day). On a mild quiet day, weather won't necessarily get mentioned — that's by design.
7. **Live refresh.** Note the chip's temperature, then wait at least an hour (or change Open-Meteo data via a different location). Reload `/` — temp/conditions/wind should update; H/L/rain-prob/best-window may stay the same (best-window advances, daily aggregates don't). The `current=` overlay call is sub-100ms so the dashboard doesn't visibly slow.
8. **Best-window advances.** Open the dashboard early in the day, note the suggested window. Reload after lunch — the window should have moved forward (no longer suggests a time that's already passed). The headline weather numbers stay the same since they're day-cached, but the best window is recomputed live.
9. **48-h modal.** Click the chip (or focus + Enter for keyboard users). A native dialog opens with horizontally-scrollable hour columns; ESC and backdrop click both close it. The best-window columns should have a green "BEST" tag overhead. A dashed accent vertical with "Tomorrow" should split today from tomorrow's columns.

## Future improvements

- **Tomorrow's sunrise/sunset.** Right now only today's sunrise/sunset markers render — the cache stores them as scalars on the top-level dict, so we'd need to keep the daily array (or both days' values) to mark tomorrow's columns too.
- **Temperature curve overlay.** The columns already show the temperature number; adding a thin SVG line across the top connecting them visually would make the warming/cooling trend pop.
- **Trip mode.** A "Use a different location today" override on the dashboard (or a small Settings toggle) — useful when you're traveling for a race or for work.
- **Weather-aware daily tip.** Today's tip card is rules-driven and weather-blind. If it's pouring, an "Active recovery walk" should become "Indoor mobility flow". Easy add once the rules layer reads `weather` too.
- **Race-day weather forecast.** For an active plan with a race date within the 16-day Open-Meteo window, surface the race-day forecast on the plan hero / dashboard countdown.
- **Air quality.** Open-Meteo also has a free air-quality API. PM2.5 / pollen would be useful for asthmatic runners.
- **Settings UX: confirm-resolved-place.** Two-step save: type → preview "We resolved this to X. Save?" → confirm. Removes the "I had to retype to get the right city" friction.
- **Runnability rule tuning.** The scoring constants in `_score_hour` are a first guess. Real users will reveal whether the temp curve is right and whether 25 km/h is the correct wind threshold. Could expose as Settings later, but more likely we adjust based on observed feedback first.

---

*Last updated: 2026-05-16*
