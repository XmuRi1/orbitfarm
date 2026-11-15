# UX Polish v1 — First-run Experience & Guided Demo

The first screen offers two explicit paths: a confirmed Beersheba historical example or the user's own point/date/crop form. The map and period share a wide site section; climate/water then use the full analytical width. Existing green/light tokens, components, expert controls and exports remain.

## Guided example

`guided-demo.ts` contains **inputs only**: 31.25, 34.79, wheat, 2025-01-01–2025-03-31; conditional SRTM v3 288 m; user Kc .3/1.1/.4 with 20/25/25/20-day phases; thetaFC=.30, thetaWP=.12, Zr=.6 m, p=.5, initial Dr=27 mm; three net 25 mm irrigations on Jan/Feb/Mar 15. Height is a DEM estimate, not a surveyed site elevation. Kc/soil/root/irrigation values are test assumptions, not measured properties or recommendations.

Opening the example does not accept sources or submit requests. An initially unchecked grouped acknowledgement lists all inputs and model simplifications. Only explicit acceptance plus launch sets the existing API acknowledgement fields. Editing relevant inputs invalidates their confirmation.

The controller calls existing season → water → root-zone routes sequentially. Every result must declare `source_is_synthetic=false`; errors stop the sequence. All numerical results come from the server. There are no embedded weather arrays, calculated totals, new scientific algorithms or backend changes. Existing exact-request memory reuse, backend parameter-specific NASA caches and shared quotas remain in force. Already dispatched HTTP requests are not claimed to be aborted; generation fencing ignores their retired responses and prevents subsequent stages.

## State ownership and readiness

`Home` owns shared context and `ScenarioDrafts`; water/root controls are controlled children. Publications retain context and exact request keys. Demo responses seed the same components by matching keys. Changing a draft clears dependent results and cancels a pending demo. Manual seasonal reruns clear dependent results while preserving compatible drafts; no calculation starts automatically.

| Change | Draft handling |
| --- | --- |
| Same site/crop/period rerun | Keep values, events and compatible acknowledgements |
| Equivalent coordinate formatting | Keep drafts |
| Different point | Clear site/crop/soil assumptions and confirmations |
| Different crop | Keep unconfirmed height and thetaFC/thetaWP drafts; clear crop Kc, root/calendar settings and all confirmations |
| Different historical dates | Keep numerical drafts and irrigation events; revoke Kc and root acknowledgements; keep site height acknowledgement |
| Height/source edit | Revoke height acknowledgement; clear water/root results |
| Kc/calendar/source edit | Revoke Kc acknowledgement; clear water/root results |
| Soil/initial state/irrigation edit | Revoke root acknowledgement; clear root result |

Out-of-period irrigation events remain visible for explicit correction and block submission. They are never silently discarded. Draft persistence is in-memory for the current page, not across reloads.

Water has four steps: site inputs → reference ET0 → potential crop ETc → soil scenarios. Missing height/source/acknowledgement is an actionable checklist. ET0 can be calculated without known Kc. Missing Kc/calendar leaves ETc unknown. Cards distinguish missing settings, missing source observations, empirical model limitations and computed conditional values; real zero remains zero. Root settings appear only after complete ET0/ETc/rain, otherwise a compact prerequisite gate links to the relevant fields. Successful settings collapse, results remain visible. Long methods, daily data, source details and JSON remain expandable. Summary compares descriptive plan indicators without choosing a winner.

`actual_water_balance` remains null; a conditional historical scenario is not an observed field balance or forecast of future rotation seasons. User dates are not automatically validated growing dates.

## Verification

From `frontend`:

```powershell
node --test tests/*.test.mjs
npm run lint
npx tsc --noEmit --incremental false
npm run build
```

Tests include prior API/session tests, production draft/demo helpers and actual React server rendering of consent, loading/errors, readiness gates and nullable metrics. They do not claim browser interaction or visual coverage.

With actual FastAPI and a production Next server:

```powershell
$env:ORBITFARM_HTTP_TEST_BASE_URL = 'http://127.0.0.1:3001'
node tests/guided-demo-http.mjs
```

This exercises the same demo builders/controller through real HTTP and accepts genuine NASA server cache entries. Expected test-scenario totals are asserted in tests only. `experience-http.mjs` separately covers the existing integrated workflow. Both share the default eight-NASA-route-requests/minute quota; allow the window to reset between complete workflows. HTTP 429 is not a NASA outage and is not retried with synthetic input.

## Video review and remaining manual checks

The supplied 97.73-second desktop recording was inspected at five-second intervals and selected full-size frames. It showed height 112 m without source/acknowledgement, unknown Kc, correctly unknown ET0/ETc despite complete NASA weather; the missing settings were hard to discover. It also showed a long disabled root form, green disabled actions, empty space below the narrow map rail, repeated context/method warnings and dense textual summaries. These observations motivated the readiness checklist/gate, explicit disabled styling, full-width analytical flow, collapsed expert details and compact plan table.

The recording did not show mobile, successful root modelling or the updated UI. Computer-use access returned `Computer Use native pipe is unavailable` during this task. Desktop/mobile layout, sticky navigation/focus, map resizing and graph/table scrolling still require a manual pass. The CSS includes mobile breakpoints; successful build/HTTP/render tests are not visual verification. No audio transcription was performed.
