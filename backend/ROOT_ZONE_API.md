# Root Zone Water Balance v1 — Scenario Mode

`POST /api/root-zone/compare` on FastAPI and the Next.js server proxy. Existing water, seasonal, scoring and rotation endpoints keep their contracts. `actual_water_balance` remains null everywhere: this endpoint estimates two user-defined historical scenarios, not measured field water availability or a future forecast.

## Method

[FAO-56 Chapter 8](https://www.fao.org/4/x0490e/x0490e0e.htm), Eqs.81–88. V1 has one homogeneous bucket, fixed effective root depth and fixed p, with no automatic crop/soil lookup. Existing single Kc and `fao56_pm_asce2005_cloud_bounds` ET0 are reused unchanged.

```text
TAW = 1000 (thetaFC - thetaWP) Zr                      Eq.82, mm
RAW = p TAW                                          Eq.83, mm
F = P + I                                            RO=CR=0 scenario assumption
Dr_for_Ks = max(0, Dr_start - F)                       explicit early-day wetting
Ks = 1                          if Dr_for_Ks <= RAW
Ks = (TAW - Dr_for_Ks)/(TAW-RAW) otherwise             Eq.84
ETc_adj_Eq81 = Ks * potential_ETc                     Eq.81, single Kc
available_this_day = TAW - Dr_start + F
ETc_adj = min(ETc_adj_Eq81, available_this_day)         additional marked daily supply cap
DP = max(0, P + I - ETc_adj - Dr_start)                Eq.88
Dr_end = Dr_start - P - I + ETc_adj + DP               Eq.85
0 <= Dr_end <= TAW                                   Eq.86
```

Rain and net irrigation precede the stress calculation. The remaining excess drains **after ET within the same day**, as specified by Eq.88. Water over field capacity may contribute to that day's ET; it is never retained in the end-of-day bucket. Dr and reported available root-zone storage stay within [0, TAW]. Do not substitute `DP=max(0,P+I-Dr_start)` followed by ET: that would impose a different drainage timing.

The daily supply cap is an explicitly recorded numerical constraint to avoid withdrawing more available water than exists during a coarse daily step. `etc_adj_eq81_mm` preserves the uncapped Eq.81 value; `available_water_cap_applied` and `daily_available_water_cap` expose any cap. It does not change the existing potential ETc/Kc/ET0 engines. With TAW=10, Dr=0, RAW=5, P=I=0 and potential ETc=1000 mm, Ks=1 but modelled extraction is limited to 10 mm, and the next day's Ks=0. This is a numerical boundary test, not realistic weather or irrigation guidance.

Eq.81 reduces the entire single-Kc ETc, although physical stress primarily affects transpiration. Separate Kcb/Ke, soil evaporation and salinity are not modelled. This limitation is carried in the response and UI. Dr is directly supplied (or supplied as a fraction of TAW); Eq.87 describes a possible measured-theta initialisation, but v1 does not invent a measured initial moisture content.

## Explicit request

Start with the same crop/location/dates/elevation/Kc fields as [WATER_API.md](WATER_API.md), then add:

```json
{
  "soil": {
    "theta_fc": 0.30,
    "theta_wp": 0.12,
    "theta_unit": "m3/m3",
    "zr_m": 0.6,
    "p": 0.5,
    "source": "TEST SCENARIO ONLY: not measured soil, roots, p or initial moisture",
    "acknowledge_assumptions": true
  },
  "initial_depletion": { "fraction_of_taw": 0.25 },
  "irrigation": [
    { "date": "2025-01-15", "net_mm": 25 },
    { "date": "2025-02-15", "net_mm": 25 },
    { "date": "2025-03-15", "net_mm": 25 }
  ],
  "assumptions": {
    "runoff_zero": true,
    "capillary_rise_zero": true,
    "full_rain_infiltration": true,
    "wetting_before_et": true,
    "same_day_drainage": true
  }
}
```

These numbers are deliberately conditional test assumptions, not Beersheba measurements or wheat requirements. The UI has no default soil values, initial depletion or irrigation amounts. Full [historical example request](examples/root_zone_beersheba_scenario.json) includes the conditional SRTM 288 m source and explicit user Kc phases.

Validation:

- Numbers must be finite JSON numbers, never booleans. `0 <= theta_wp < theta_fc <= 1`, volumetric units exactly `m3/m3` (percentages are rejected); `zr_m > 0` metres. Derived TAW and stress denominator must be finite and positive.
- `0 <= p < 1`. p=1 is unsupported because Eq.84 has a zero denominator; p=0 is supported. No automatic ET-based p adjustment.
- `initial_depletion` contains **exactly one** of `dr_mm` in [0,TAW] or `fraction_of_taw` in [0,1]. No implicit initial state. The soil source/acknowledgement covers the soil, effective roots, p and initial-state scenario.
- `irrigation` is required; `[]` explicitly means no irrigation. Each event has only a strict ISO `date` within the selected interval and finite nonnegative `net_mm`. Dates are unique, at most one event per day. No application-efficiency conversion or suggested timing/depth is applied.
- All five assumptions must explicitly be true. False/omitted values are rejected rather than silently ignored. They describe scenario simplifications, not verified site properties. All daily rain, including small amounts, infiltrates; no effective-rainfall estimator is introduced.
- Season, crop, height and Kc validation reuse existing water contracts. No weather/ET arrays submitted by a client are used: FastAPI creates one canonical daily water assessment and reuses it for both scenarios.

## Response

`pipeline=orbitfarm_root_zone_scenario_v1`, `mode=scenario_not_measured`, `not_a_forecast=true`, `method.policy=fao56_root_zone_single_kc_early_wetting_v1`.

- `soil` retains input assumptions, source, TAW/RAW and `status=user_assumption`.
- `initial_depletion` records the entered representation and `dr_mm_used`.
- `scenarios.rainfed` and `scenarios.irrigated` share exactly the same weather, crop, soil, fixed roots/p and initial Dr. Only net irrigation differs. Their `daily` arrays contain date, `dr_start_mm`, `dr_after_wetting_mm`, `dr_end_mm`, `available_water_end_mm`, `taw_mm`, `raw_mm`, `precipitation_mm`, `net_irrigation_mm`, `deep_percolation_mm`, `potential_etc_mm`, `ks`, `etc_adj_eq81_mm`, `etc_adj_mm`, supply-cap marker, status, stress status, quality flags and reasons.
- Stress status is `modelled_stress` exactly when Ks<1 at the chosen after-wetting stress evaluation. `no_modelled_stress` does not claim measured absence of field stress. The chart shows **end-of-day** Dr, so crossing RAW on the chart is not itself a count of stress days.
- `mass_balance_residual_mm = Dr_end - Dr_start + P + I - ETc_adj - DP`. Nonrepresentable numeric balances are unknown, not silently filled. `provenance_ref=shared_inputs` resolves to the shared source URL, units, method, Kc assumptions, elevation provenance and user soil source. Daily `water_diagnostics` retain upstream reasons and cloud correction, and `quality_flags` inherit the ETc flags.
- Each summary contains initial/final Dr, full-period `stress_days`, partial `observed_stress_days`, ETc_adj/DP period totals using the existing complete/partial/unknown convention, total net irrigation, and the maximum absolute daily mass residual. Whole-period totals/counts are null for an incomplete model; partial ET totals are labelled separately.
- `differences` are **B minus A**, explicitly labelled: stress days, total ETc_adj, final Dr, net irrigation and DP. Unknown operands yield null differences. They are not a field-water deficit, yield estimate or irrigation prescription.
- `coverage.nasa.observations/inputs` reports NASA coverage separately from `coverage.et0`, `coverage.potential_etc`, precipitation and `coverage.root_zone.rainfed/irrigated`. Data completeness does not assert model validity.
- `actual_water_balance=null`. No salinity, yield or economic results are produced.

## Incomplete data and errors

HTTP modelling starts only with complete, finite ET0, potential ETc and precipitation for the exact historical period and all explicit scenario parameters. Otherwise **422 `root_zone_inputs_incomplete`** contains `missing_requirements` and separate coverage, with zero modelled days. The UI disables submission and explains missing height/ET inputs, Kc/calendar or rain before calling the API.

Independently, the pure `simulate_scenario` kernel preserves an unknown suffix if a mandatory day is missing/invalid: that day's end state, Ks, ETc_adj and DP become null; following days carry `previous_root_zone_state_unknown`, even after heavy rain. There is no interpolated weather, assumed state or automatic reset to field capacity. Known dates, input values, soil constants and net irrigation remain visible.

400/413 retain existing input/body-size conventions. NASA errors remain 502 `nasa_upstream_unavailable`, without synthetic fallback; root-zone requests share the existing NASA limiter, 429 with `Retry-After`. Next.js preserves JSON/status/diagnostics; backend 404 remains `root_zone_route_not_found` rather than a NASA error. OpenAPI generation includes the new route; public OpenAPI remains disabled as before.

## Validation and historical scenario

Example 37: thetaFC=0.32, thetaWP=0.12, Zr=0.8 m, p=0.4, initial Dr=55 mm, ET0=5, Kc=1.2, P=I=0. TAW=160 mm, RAW=64 mm. First two days ETc_adj=6 mm, end Dr=61 and 67 mm; third Ks=0.96875, ETc_adj=5.8125 mm. All ten days agree with the rounded FAO table (final Dr approximately 104.5 mm).

For the saved real Beersheba NASA quarter, the explicitly conditional soil example above gives TAW=108 mm, RAW=54 mm and initial Dr=27 mm. The pre-existing user Kc scenario and SRTM height are unchanged. NASA contains 810/810 values; potential ETc=176.8946371277 mm, rain=76.18 mm, and both root models cover 90/90 days:

| Result | A: Rainfed | B: three 25 mm irrigations |
| --- | ---: | ---: |
| Days with Ks<1 | 31 | 8 |
| Modelled ETc_adj, mm | 140.1645770526 | 174.2191723683 |
| Initial Dr, mm | 27 | 27 |
| Final Dr, mm | 90.9845770526 | 69.8880869024 |
| Total net irrigation, mm | 0 | 75 |
| DP, mm | 0 | 19.8489145342 |

Water conservation: P+I = ETc_adj+DP+Dr_initial−Dr_final. Maximum daily residual is below 1e−14 mm in this example. The comparison does not prove that this soil, initial state, p, depth or schedule describes an actual field.

Tests cover Example37, random and seasonal mass conservation, rain saturation/DP, early irrigation, dry periods, TAW, RAW and p boundaries, missing-state propagation, bad physical values/units/dates, numeric overflow, zero-irrigation equality, incomplete-input rejection, shared quota, original API compatibility and replay of the saved NASA quarter through actual FastAPI/Next.js processes.

```powershell
.\backend\.venv\Scripts\python.exe -B -m unittest discover -s backend/tests -q
cd frontend
node --test tests/season-proxy.test.mjs tests/water-proxy.test.mjs tests/root-zone-proxy.test.mjs
npm run lint
.\node_modules\.bin\tsc.cmd --noEmit --incremental false
npm run build
cd ..
.\backend\.venv\Scripts\python.exe -B backend/tests/smoke_local_stack.py
```

## Future Rotation Planner integration

Use each season's explicit crop/Kc/calendar and the same site/weather when comparing management scenarios. A future adapter must define carry-over Dr between seasons, off-season weather/irrigation, changed root-zone depths and layers, and provenance for each crop's parameters. A changed Zr cannot simply reuse the same depletion fraction without accounting for water in the added/removed soil layer. Keep scenario outputs independent of existing rotation scoring/unknown statuses; no rotation ranking, yield or economic benefit follows automatically from this module.
