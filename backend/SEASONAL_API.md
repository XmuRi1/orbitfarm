# Seasonal Climate Engine v1

`POST /api/season/assess` is a separate FastAPI endpoint. The Next.js server proxies the same path. Existing `/api/assess`, `/api/nasa/assess`, and rotation responses keep their contracts. Scoring, weights, crop catalogue and rotation rules are unchanged.

## Request

```json
{
  "crop_id": "wheat",
  "latitude": 31.25,
  "longitude": 34.79,
  "sowing_date": "2025-01-01",
  "end_date": "2025-01-05",
  "historical_period": { "start": "2025-01-01", "end": "2025-01-05" }
}
```

These dates are an API example, not recommended sowing dates. The user must supply the historical growing window. Dates are strict `YYYY-MM-DD`, inclusive, between 1981-01-01 and yesterday; maximum 366 days. Cross-year windows and leap days are supported. `crop_id` must exist in `data/crops.json`. Coordinates must be finite JSON numbers within latitude/longitude bounds. `historical_period` is optional; if present, it must exactly match the two season dates. It never selects an unrelated period for analysis. Growth stages, planting dates, maturity and thresholds are not inferred.

## Daily data and storage

The existing NASA POWER Daily Point request retrieves `T2M`, `T2M_MIN`, `T2M_MAX`, `PRECTOTCORR`, `RH2M`, and `ALLSKY_SFC_SW_DWN` with community `AG` and explicit `time-standard=LST`. [NASA documents the daily API and LST/UTC standards](https://power.larc.nasa.gov/docs/services/api/temporal/daily/). LST is local solar time, not the browser's civil timezone. A conflicting response time standard is an upstream error; absent response metadata is labelled `time_standard_basis=explicit_request` rather than claimed as verified.

The original NASA response uses the existing 14-day exact-coordinate/date cache. The seasonal path additionally writes `backend/cache/nasa_power/power_<key>.daily.json`. Both are best-effort on read-only/ephemeral deployments. A response URL is retained across raw-cache reads, including older cache entries without that extra metadata. Existing aggregate responses do not receive new daily fields.

`daily.parameters` contains six arrays with one row for every requested date, in chronological order. Each row has `date`, `value` (number or `null`), and `missing_reason`. Parameter metadata includes canonical `parameter_id`, NASA key, source and normalized units, conversion factor, daily aggregation, ignored out-of-window/invalid date keys, and coverage/missing dates.

Temperature units are `°C`; humidity `%`; daily precipitation `mm/day`; radiation `MJ/m²/day`. Only explicitly declared kWh radiation is multiplied by 3.6. Seasonal precipitation uses the existing canonical `CLIM_007` unit `mm per period`. Missing source units are not guessed. Missing dates, NASA fill values, non-numeric/non-finite values and invalid physical values (negative precipitation/radiation, humidity outside 0–100%) become `null`, never zero or interpolated observations. The synthetic test-fixture flag is preserved by the pure normalizer and rejected by the live fetch/cache path. There is no synthetic fallback.

## Response

The full, generated [fixture example](examples/season_assessment_fixture.json) is labelled `source_is_synthetic=true`; its values are for testing, not real farm observations.

Top-level fields:

| Field | Meaning |
| --- | --- |
| `schema_version`, `pipeline`, `mode` | `1.0.0`, `orbitfarm_seasonal_climate_v1`, `historical_daily_description` |
| `crop`, `location`, `historical_period` | Selected catalogue crop and exact requested point/window |
| `season` | Sowing/end dates, inclusive `duration_days`, `growth_stages=unknown` |
| `metrics` | Seven statistics with values, units, aggregation, completeness and reasons |
| `coverage` | Valid/expected day-parameter values, fraction, days with all six parameters and per-parameter missing dates |
| `daily` | Normalized date-indexed source observations and metadata |
| `source`, `source_is_synthetic`, `retrieved_from_cache` | Explicit provenance/cache state |
| `crop_requirements` | Catalogue data, nullable references/comparisons and reasons for `unknown` |
| `suitability_score_0_100`, `water_balance` | Always `null` in v1 |
| `not_a_forecast`, `limitations` | Always historical; scope and data limitations |

Each metric contains `parameter_id`, `value`, `observed_value`, `unit`, `aggregation`, `status` (`complete`, `partial`, `missing`), `days_available`, `days_expected`, and nullable `reason`.

| Metric | Actual daily input and rule |
| --- | --- |
| `mean_temperature` | Arithmetic mean of available `T2M` |
| `minimum_temperature` | Minimum of available daily `T2M_MIN`, never inferred from `T2M` |
| `maximum_temperature` | Maximum of available daily `T2M_MAX`, never inferred from `T2M` |
| `total_precipitation` | Sum of `PRECTOTCORR`; full-season `value=null` if any day is missing |
| `rainy_days` | Count of `PRECTOTCORR > 0 mm`; full-season `value=null` if any day is missing |
| `mean_solar_radiation` | Mean of available normalized daily radiation totals |
| `mean_relative_humidity` | Mean of available `RH2M` |

Available-day means/extremes remain visible when partial; they do not claim to describe missing days. `observed_value` records only the available-day statistic, including partial precipitation sums/counts. If no observations exist, both values are `null`. The rain-day definition is a descriptive counting convention, not an invented crop stress threshold. Coverage measures data availability, not scientific confidence. Extremes must not be described as confirmed full-season extremes when their daily series is incomplete.

Requirements use `CLIM_001/002/003/007/008/009` and `WATER_007` from the unchanged catalogue. A missing requirement has `requirement=null`, `reference=null`, `comparison=null` and an explicit reason. Unverified requirements, incompatible units, unspecified aggregation/time window, unknown required growth stages, or incomplete observations block comparison and produce `status=unknown`. Draft reference ranges can be shown as unverified source information but are not critical boundaries. A descriptive range comparison is possible only for a verified, compatible complete-season reference; it never produces a suitability score. Current catalogue requirements remain blocked. Precipitation is never compared directly with crop water demand.

## Errors and verification

A proxy response `404 season_route_not_found` means the configured backend does not have the seasonal route; it is not a NASA failure. Check `ORBITFARM_BACKEND_URL` and restart the current `backend/app.py` with the root README's Uvicorn command (`--reload` for local development). Restart Next.js if its backend URL changed. A process started before the endpoint was added, without reload, continues serving its old route table. `/openapi.json` is intentionally disabled in this MVP; inspect `app.openapi()['paths']['/api/season/assess']` programmatically, then verify a real POST (an empty object should return 400, not 404).

The frontend displays HTTP 404 separately from upstream NASA 502. Run `node --test tests/season-proxy.test.mjs` in `frontend/` for route-handler regression checks, including JSON and HTML 404 bodies. The local stack smoke test additionally simulates an old backend with its seasonal route removed and checks the proxy's actual HTTP 404.

Errors retain `{ "error": "...", "detail": "..." }`: HTTP 400 for invalid input, 413 for oversized/empty bodies, 429 with `Retry-After` for the shared NASA quota, and 502 `nasa_upstream_unavailable` with `used_synthetic_fallback=false` for network/format/time-standard failures. Next.js additionally returns 503 `backend_not_configured` or 502 `backend_unavailable` / `invalid_backend_response`. It forwards backend status and `Retry-After`.

Run the canonical suite and frontend checks from the root README. `backend/tests/smoke_local_stack.py` launches real FastAPI and Next.js on temporary ports with the explicitly test-only launcher `serve_smoke_app.py`. NASA success, missing precipitation and upstream errors are mocked in that launcher; no mock is enabled through production settings or public request fields. Test scripts and fixtures are excluded from the Vercel backend bundle. The smoke check covers seasonal proxy success/errors alongside existing routes and rotation plans, then stops its processes. A live NASA connection and a deployment are separate checks.
