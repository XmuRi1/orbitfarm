# Water Balance Engine v1: reference ET0 and potential ETc

This module is **not** a root-zone soil water balance. `actual_water_balance` is always `null`. It never reports rainfall minus ETc as actual field deficit, nor equates total precipitation to effective rainfall. Existing scoring, weights, crop requirements and rotation rules are unchanged.

## Method and authoritative references

- [FAO-56 Chapter 2, Eq. 6: Penman–Monteith](https://www.fao.org/4/x0490e/x0490e06.htm).
- [Chapter 3: meteorological quantities, Eqs. 8–14, 21–25, 37–42 and low-wind guidance](https://www.fao.org/4/x0490e/x0490e07.htm).
- [Chapter 4: Example 18, daily ET0](https://www.fao.org/4/x0490e/x0490e08.htm).
- [Chapter 6: single Kc, Eqs. 58 and 66, Example 28](https://www.fao.org/4/x0490e/x0490e0b.htm).
- [NASA POWER Daily Point API](https://power.larc.nasa.gov/docs/services/api/temporal/daily/).
- [ASCE-EWRI 2005, pp. 19–20, Eqs. 17–18: cloud-ratio bounds](https://content.mesonet.org/mesonet/site_files/ASCE_Evapotranspiration_Formula.pdf#page=30).

All calculations use daily historical data in explicit LST. They describe the FAO hypothetical, well-watered, short-grass reference surface (height 0.12 m, albedo 0.23, surface resistance 70 s/m), not actual evaporation from the selected field.

```text
ET0 = [0.408 Δ (Rn - G) + γ 900/(Tmean + 273) u2 (es - ea)]
      / [Δ + γ (1 + 0.34 u2)]                         mm/day

Tmean = (Tmax + Tmin)/2                             Eq. 9
e°(T) = 0.6108 exp[17.27 T/(T + 237.3)]             kPa, Eq. 11
es = [e°(Tmax) + e°(Tmin)]/2                        kPa, Eq. 12
ea = e°(Tdew)                                      kPa, Eq. 14
Δ = 4098 e°(Tmean)/(Tmean + 237.3)^2                 kPa/°C, Eq. 13
γ = 0.000665 P                                     kPa/°C, Eq. 8

J = actual day of year; φ = latitude in radians
dr = 1 + 0.033 cos(2πJ/365)                         Eq. 23
δ = 0.409 sin(2πJ/365 - 1.39)                       Eq. 24
ωs = acos[-tan(φ) tan(δ)]                           Eq. 25
Ra = (24×60/π) 0.0820 dr [ωs sinφ sinδ + cosφ cosδ sinωs]   Eq. 21
Rso = (0.75 + 2×10^-5 z) Ra                         Eq. 37
Rns = (1 - 0.23) Rs                                Eq. 38
r_cloud = max(0.3, min(Rs/Rso, 1.0))                ASCE-EWRI 2005 Eq. 18
Rnl = 4.903×10^-9 [(Tmax+273.16)^4+(Tmin+273.16)^4]/2
      × (0.34 - 0.14 sqrt(ea)) × (1.35 r_cloud - 0.35)       Eq. 39 with cloud bounds
Rn = Rns - Rnl                                     Eq. 40
G = 0 for the daily reference surface               Eq. 42
```

Ra, Rs, Rso, Rns, Rnl, Rn and G are MJ/m²/day. The astronomical equations retain FAO's 365-day denominator; J is the actual ordinal day, including leap years. The acos argument is bounded to [-1,1] for polar geometry. A zero Rso (polar night) cannot establish cloudiness and produces `null`.

NASA `T2M_MIN/MAX` determine Tmean and saturation pressure. NASA `T2M` and `RH2M` are retained as context; they do not replace missing extremes or dewpoint. PS supplies actual source surface pressure; pressure is not estimated from height. A site height with source and explicit user confirmation is independently required for Rso. No sea-level height is assumed and no height is inferred from PS or unverified grid metadata. User confirmation is recorded as `user_asserted_not_independently_verified`, not independent validation of the location.

For an **observed** non-negative wind below 0.5 m/s, the method applies FAO Chapter 3's minimum 0.5 m/s, recording both raw input and used value plus a quality flag. Missing wind is never replaced by 0.5.

The fixed policy is **`fao56_pm_asce2005_cloud_bounds`**, identified by `method.policy` and each day's `cloud_correction.policy`. Only the ratio inside Rnl's cloud factor is bounded to **[0.3, 1.0]**, following ASCE-EWRI 2005. Original daily Rs, computed Rso, and Rns=0.77Rs are unchanged. A ratio of 0.3 gives a cloud factor of **0.055**, not 0.05. This lower bound is not presented as an explicit requirement of the original daily FAO-56 Eq.39 text. All other FAO-56 constants remain unchanged, including sigma=4.903e-9; this is not a full switch to all ASCE constants or another ET method. No implicit policy fallback or legacy strict mode is exposed.

V1 still returns `null` with diagnostic reasons for missing/incompatible inputs, missing sourced height, inconsistent vapour pressure, negative/non-finite ET0, zero Rso, or a negative empirical humidity factor in Eq.39. It does not reconstruct missing observations, model condensation, or switch to Hargreaves/other methods. The daily G approximation is not a soil water storage calculation.

## Request: POST /api/water/assess

Same endpoint on FastAPI and the Next.js server proxy. The crop ID, coordinates and historical dates follow the seasonal contract: strict ISO dates, inclusive, ending before today, at most 366 days, catalogue crop ID. Optional `historical_period` must exactly match sowing/end dates.

The minimal valid request computes precipitation but correctly leaves ET0 unknown without a sourced height, and ETc unknown without Kc/calendar:

```json
{
  "crop_id": "wheat",
  "latitude": 31.25,
  "longitude": 34.79,
  "sowing_date": "2025-01-01",
  "end_date": "2025-01-05",
  "elevation": null,
  "kc_scenario": null
}
```

For ET0, provide your **actual known** elevation:

```json
{
  "value_m": 100,
  "source": "EXAMPLE ONLY: replace with the real elevation source for your site",
  "confirmed": true
}
```

This is only a structural example, not an assertion that the example point is at 100 m. Omitted/null height, missing source or no explicit confirmation yield unknown ET0, without blocking precipitation. Supplied malformed/non-finite height values are HTTP 400; v1 supports land elevations -500..9000 m. Source text and confirmation are not automatic scientific verification. NASA pressure is from its model grid and is not automatically corrected to the user's elevation.

Optional ETc uses an explicit, grass-reference scenario:

```json
{
  "type": "user_defined",
  "reference_surface": "grass",
  "crop_id": "wheat",
  "source": "EXAMPLE ONLY: a synthetic five-day scenario, not wheat guidance",
  "acknowledge_assumptions": true,
  "kc_initial": 0.3,
  "kc_mid": 1.1,
  "kc_end": 0.4,
  "stage_lengths_days": { "initial": 1, "development": 1, "mid": 2, "late": 1 }
}
```

These are invented **test-scenario inputs**, never production defaults or catalogue requirements. The UI starts empty. Production does not import test fixtures or provide a mock switch. Crop ID must match the request. Each known stage length is an integer 1..366 days; the four lengths must cover the exact requested interval. Known Kc values must be finite and non-negative. The four stages run consecutively from the user's sowing date. No stage dates or durations are inferred.

Initial and mid-stage Kc are constant. Development goes linearly from Kc_initial to Kc_mid; late goes linearly from Kc_mid to Kc_end:

```text
Kc(i) = Kc_prev + [(i - sum(previous stage lengths))/current stage length]
                  × (Kc_next - Kc_prev)             FAO-56 Eq. 66
ETc(i) = ET0(i) × Kc(i)                             FAO-56 Eq. 58
```

Day numbering is 1-based. Missing Kc, source, acknowledgement or stage calendar leaves ETc `null` with a reason while ET0 is still computed independently. An incomplete/mismatching calendar is not extrapolated to fill the rest of the season. Wrong crop ID, negative/non-finite Kc and invalid stage lengths are HTTP 400. Grass reference is implied if the optional `reference_surface` field is omitted; explicitly alfalfa coefficients are rejected, never silently converted. No climatic Kc corrections, wetting-frequency corrections or verified crop-specific coefficients are inferred. ETc is conditional potential demand under standard, non-stressed conditions, not actual crop water use.

## NASA inputs and versioned cache

Water requests use nine parameters: the original `T2M, T2M_MAX, T2M_MIN, RH2M, PRECTOTCORR, ALLSKY_SFC_SW_DWN`, plus `WS2M, T2MDEW, PS`. Existing routes continue to request/return only their original six normalized series; old successful JSON shapes are preserved.

| Parameter | Required for ET0 | Normalized unit | Accepted declared source units |
| --- | --- | --- | --- |
| T2M_MIN, T2M_MAX | yes | °C | C, °C |
| T2MDEW | yes | °C | C, °C |
| WS2M | yes, at 2 m | m/s | m/s, m s-1 |
| PS | yes | kPa | kPa; Pa ×0.001; hPa or mb ×0.1 |
| ALLSKY_SFC_SW_DWN | yes | MJ/m²/day | existing MJ units; explicit kWh units ×3.6 |
| PRECTOTCORR | no, reported separately | mm/day | mm/day, mm d-1 |
| T2M, RH2M | context only | °C, % | existing accepted units |

Missing units never imply a conversion. Fill values, absent dates, non-finite values, negative wind/radiation/rain and non-positive pressure become explicit missing observations. WS2M maps to existing `CLIM_011`; derived ET0 corresponds to `CLIM_010`. Dewpoint and PS are NASA transport inputs with `parameter_id=null` because the unchanged crop registry has no corresponding entries. No new crop requirements are invented.

Raw and normalized caches use schema v2 (`power_v2_<hash>.json` and `.daily.json`). Keys include the full requested parameter set, schema version, exact coordinates/dates, AG community and LST standard. Stored profile metadata is checked on read. Six- and nine-parameter requests cannot reuse one another's cache. Old unversioned files are left untouched but not reused. Cache persistence remains best-effort with a 14-day TTL. Missing data and synthetic flags remain explicit. Synthetic source payloads are rejected by the live pipeline; only isolated tests simulate upstream responses.

## Response and completeness

The full [synthetic fixture response](examples/water_assessment_fixture.json) has `source_is_synthetic=true`. A [live no-height response](outputs/water_live_verified.json), when locally generated, is ignored by Git and must not be confused with the fixture.

- `pipeline=orbitfarm_water_demand_v1`, `mode=historical_reference_et0_and_potential_etc`, `not_a_forecast=true`.
- `daily`: exact date, normalized inputs, ET0 (`et0_mm`), precipitation depth (`precipitation_mm`), Kc, stage, potential ETc (`etc_mm`), diagnostics and intermediate quantities with units in their keys. Daily ET0 and ETc represent mm/day over each one-day interval.
- `et0`, `potential_etc`, `precipitation`: separate `total_mm`, `observed_total_mm`, unit `mm per period`, available/expected days, fraction, status and reason codes. No differences are computed.
- `total_mm` is non-null only if **every** requested day is computable. `observed_total_mm` describes valid days only, never a complete-season total. No available values means both are `null`. Summation uses unrounded calculations and `math.fsum`; non-finite results are unknown, never serialized as Infinity.
- Missing precipitation does not block ET0 or ETc; missing required ET0 inputs block ET0/ETc for that day. Missing Kc/calendar does not block ET0.
- `coverage.inputs` reports availability for all nine NASA series; `coverage.et0_days/etc_days/precipitation_days` distinguishes the three outputs. In particular, 100% weather availability does not imply computable ET0 when height is unknown.
- `coverage.observations` separately reports `available_values`, `expected_values` (9 × requested days), `complete_days` (all nine compatible normalized observations), and `coverage_fraction` (available/expected values). Context-only T2M/RH2M or precipitation gaps reduce observation completeness without necessarily blocking ET0.
- `coverage.cloud_ratio_bounded_days` and `cloud_ratio_bounded_dates` count/list days when the bound was actually evaluated and applied. They are separate from calculation coverage; applying a bound is not missing weather and does not imply a fully validated field estimate.
- Every `daily[].cloud_correction` contains `policy`, `rs_rso_raw`, `rs_rso_used`, `bounded`, `reason`, `cloud_factor_raw` and `cloud_factor_used`. With no usable weather/height, ratios and `bounded` are null and `reason=not_evaluated`; this does not claim the bound was applied. Otherwise `bounded` is boolean and `reason` is `rs_rso_below_0_3`, `rs_rso_above_1_0`, or null for an unchanged ratio. Existing `intermediates.rs_rso_raw/used` are retained.
- `daily[].quality_flags` includes `cloud_ratio_bounded_asce2005` whenever either bound is applied. The previous upper-cap flag `rs_rso_capped_at_1_per_equation_39` is preserved for compatibility. Computed ETc inherits ET0's flags through `etc_quality_flags` and shares the day's cloud diagnostics; Kc remains explicitly `kc.status=user_assumption`. Without computable ETc, `etc_quality_flags=[]`, with its unknown reasons preserved.
- `input_parameters`, `nasa_daily`, `source`, `source_is_synthetic`, `retrieved_from_cache`, `method`, `elevation` and `kc` preserve units, original metadata, conversions, assumptions and provenance.
- `actual_water_balance=null` always. No irrigation prescription, effective rainfall, root-zone storage, runoff, deep percolation, capillary rise, salinity, water stress or suitability score is produced.

Input errors use the existing 400/413 JSON conventions. NASA failures are 502 `nasa_upstream_unavailable` with `used_synthetic_fallback=false`. The quota is shared with both existing NASA endpoints; 429 includes `Retry-After`. Next.js forwards successful JSON/status, rate headers and upstream errors; HTTP 404 is explicitly `water_route_not_found`, not a NASA outage. Public OpenAPI remains disabled; `app.openapi()` includes the new path.

## Validation

FAO Example 18 is independently reproduced with published Tmin=12.3, Tmax=21.5 °C, Rs=22.07 MJ/m²/day, u2=2.078 m/s, P=100.1 kPa, latitude 50.8°N, elevation 100 m, J=187. The book's ea=1.409 kPa (from RHmax/min) is converted to its equivalent dewpoint solely for this benchmark. Computed ET0 is 3.879693 mm/day versus the published 3.88; Ra, Rso, Rn, es, ea, Δ and γ are also checked. This is a station benchmark, not a claimed height for the UI's Beersheba example point.

FAO Example 28's dry-bean curve yields Kc=0.15, 0.774 (book rounds to 0.77), 1.19, 0.56 at days 20, 40, 70, 95. This checks curve arithmetic; it does not apply dry-bean recommendations to other crops.

The committed [real Beersheba regression fixture](tests/fixtures/beersheba_2025_q1_real.json) preserves NASA's actual nine-parameter response, source URL and retrieval time. It is not synthetic. Its SRTM 288 m elevation is a conditional DEM assumption, not a surveyed site height; Kc 0.3/1.1/0.4 and phases 20/25/25/20 are explicit user assumptions, not wheat guidance. For 2025-03-07 the policy yields ET0=1.6105044281 and ETc=1.7715548709 mm/day; for the 90-day quarter ET0=233.2635497864 and ETc=176.8946371277 mm. Observations are 810/810, calculation 90/90, bounded days 1/90. The fixture is replayed only in isolated regression/HTTP tests, never substituted by production code.

Run the full canonical Python suite and frontend checks as in the root README. Run `node --test tests/season-proxy.test.mjs tests/water-proxy.test.mjs` from `frontend/`, then the local stack smoke script after building. The latter uses real FastAPI/Next processes with explicit test-only NASA mocks and verifies complete/partial ET0/ETc, unknown elevation/Kc, missing rain, error propagation and original APIs. A live nine-parameter NASA check is separate; without a user-supplied known site height, live ET0 correctly remains unknown rather than inventing elevation.
