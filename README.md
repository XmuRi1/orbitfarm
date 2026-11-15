# OrbitFarm

NASA POWER climate assessment prototype with a Next.js frontend and Python backend. The crop scoring model and requirements remain exploratory and are not an agronomic recommendation.

The integrated page follows **Участок → Климат и вода → Севооборот → Итоги** with one shared historical point/period/crop and explicit scenario assumptions. See [frontend orchestration and state checks](frontend/INTEGRATED_EXPERIENCE.md). No integrated scientific suitability score or future rotation-water forecast is produced.

## Repository layout

```text
backend/   Canonical Python code, FastAPI API, NASA POWER adapter, data and tests
frontend/  Next.js App Router, interactive Leaflet map, server-side API proxy
api_server.py  Compatibility launcher for backend/app.py:app (no separate API implementation)
```

Generated NASA caches, assessment outputs, Python bytecode, virtual environments, node_modules, Next build files, and environment files are excluded by the root `.gitignore`. Only `.env.example` files are intended for version control; never put tokens or credentials in them.

## Local development

Requirements: Python 3.12+ (Python 3.15 works locally; deployment uses 3.14), Node.js 20.9+, and npm. Run commands from the repository root unless a block says otherwise. No virtual-environment activation or `PYTHONPATH` is required.

First-time backend setup (skip creating the virtual environment if `backend/.venv` already exists):

```powershell
python -m venv backend/.venv
.\backend\.venv\Scripts\python.exe -m pip install -r backend/requirements-local.txt -r backend/requirements-test.txt
```

Start the primary FastAPI API, used both locally and by Vercel:

```powershell
.\backend\.venv\Scripts\python.exe -m uvicorn app:app --app-dir backend --host 127.0.0.1 --port 8000 --reload
```

`GET http://127.0.0.1:8000/health` checks the API process, not NASA reachability. On Windows, `backend/start_api_windows.bat` starts the same FastAPI app using the existing venv (without reload). The root compatibility command `.\backend\.venv\Scripts\python.exe api_server.py` also starts FastAPI on port 8000.

In a second terminal opened at the repository root, configure and start the frontend:

```powershell
cd frontend
npm ci
if (-not (Test-Path .env.local)) { Copy-Item .env.example .env.local }
```

Set `ORBITFARM_BACKEND_URL=http://127.0.0.1:8000` in `frontend/.env.local`, then run from `frontend/`:

```powershell
npm run dev
```

Open http://127.0.0.1:3000. The browser calls the relative Next routes `/api/assess`, `/api/rotation/options`, and `/api/rotation/compare`. The Next server forwards them to FastAPI; `/api/assess` maps to backend `/api/nasa/assess`. The environment variable is server-only. Restart Next.js after changing it.

If these ports are already occupied, use another backend port (for example `--port 8001` in the Uvicorn command) and set `ORBITFARM_BACKEND_URL=http://127.0.0.1:8001` in `frontend/.env.local`. In the frontend terminal you can also set `$env:ORBITFARM_BACKEND_URL='http://127.0.0.1:8001'` for that session, then run `npm run dev -- --port 3001` and open http://127.0.0.1:3001. Both compatibility launchers accept Uvicorn arguments too: `backend/start_api_windows.bat --port 8001` or `.\backend\.venv\Scripts\python.exe api_server.py --port 8001`. Avoid starting a second dev server for this checkout while another `next dev` is using its `.next/dev` directory; use the production smoke test for an isolated check instead.

To serve the production build locally, run `npm run build` then `npm run start -- --hostname 127.0.0.1 --port 3001` in `frontend/`, with the same backend URL configuration. This can run alongside an existing development server.

FastAPI routes:

| Method | Backend path | Purpose |
| --- | --- | --- |
| GET | `/health` | Process availability |
| GET | `/api/crops` | Catalogue of 10 crops |
| GET | `/api/nasa/status` | Integration metadata |
| POST | `/api/assess` | Farm observations to existing scoring engine |
| POST | `/api/nasa/assess` | Historical NASA observations and assessment |
| GET | `/api/rotation/options` | Catalogue and example plans |
| POST | `/api/rotation/compare` | Descriptive comparison of demo/custom plans |
| POST | `/api/season/assess` | Daily historical climate for a user-defined growing season |
| POST | `/api/water/assess` | Daily FAO-56 reference ET0 and explicit scenario potential ETc |
| POST | `/api/root-zone/compare` | Two explicit historical root-zone water scenarios, not a measured field balance |

`backend/api_server.py` is retained as the legacy stdlib diagnostic server on port 8765, including its old HTML dashboard and compatibility tests. It does not implement rotation routes and is not the backend for the Next.js application. Shared request validation lives in `backend/api_contracts.py`; FastAPI does not import the legacy server. Python implementation and tests live only in `backend/`.

## Verification

From the repository root:

```powershell
.\backend\.venv\Scripts\python.exe -B -m unittest discover -s backend/tests -v
cd frontend
node --test tests/season-proxy.test.mjs tests/water-proxy.test.mjs tests/root-zone-proxy.test.mjs tests/experience-state.test.mjs
npm run lint
npx tsc --noEmit --incremental false
npm run build
cd ..
.\backend\.venv\Scripts\python.exe -B backend/tests/smoke_local_stack.py
```

The setup above installs `backend/requirements-test.txt` for ASGI tests. The smoke script requires the production frontend build and Node.js. It launches real FastAPI and Next.js processes on temporary loopback ports, checks all backend routes and the Next.js proxies (two custom plans, all three demos, seasonal daily statistics/coverage, `unknown` statuses, and error propagation), then stops its processes. NASA is explicitly mocked by the test-only launcher for reproducible seasonal success, partial observations and upstream errors; no live NASA connection is claimed. Production has no fixture switch or synthetic fallback. Unit tests additionally cover cache persistence, units, dates and existing aggregate contracts.

## Seasonal Climate Engine v1

The compact **Сезонный анализ** section uses the selected point from the main form and explicitly entered crop/sowing/end dates. It shows actual daily-series statistics, coverage, source and limitations; it does not infer growth stages or calculate suitability. Both dates are included, up to 366 historical days. The existing aggregate analysis and Rotation Planner are unchanged.

`POST /api/season/assess` is available through FastAPI and the same-path Next.js proxy. See [the JSON contract and completeness rules](backend/SEASONAL_API.md) and [the explicitly synthetic response example](backend/examples/season_assessment_fixture.json). Daily rows retain canonical parameter IDs and missing dates/units, with no interpolation. Full-season precipitation sums/counts remain unknown when days are missing. The raw NASA cache is reused; a normalized `.daily.json` cache is also saved best-effort.

## Water Balance Engine v1

The expandable **Баланс влаги в почве** section adds Root Zone Water Balance v1 Scenario Mode: explicit soil/root/initial-state assumptions, rainfed versus a user-entered net-irrigation schedule, daily depletion chart and RAW. It requires complete ET0, potential ETc and rain, retains `actual_water_balance=null`, and does not change rotation/scoring. See [ROOT_ZONE_API.md](backend/ROOT_ZONE_API.md) for the request, FAO-56 timing, conservation tests and conditional Beersheba example.

The seasonal result includes a compact **Потребность в воде** block. It computes daily grass-reference ET0 using FAO-56 Penman–Monteith only when weather and a known, sourced, user-confirmed site elevation are available. Height is never defaulted to sea level or inferred from pressure. Optional Kc and four-stage lengths are entered in a collapsed, explicit user-scenario form; potential ETc remains unknown otherwise. No catalogue Kc or crop stage duration is assumed.

`POST /api/water/assess` works through FastAPI and the same-path Next.js proxy. See [the method, full JSON contract and limitations](backend/WATER_API.md) and [synthetic fixture response](backend/examples/water_assessment_fixture.json). Water requests add WS2M, T2MDEW and PS with checked units. Versioned cache profiles distinguish original six-parameter and new nine-parameter requests. ET0, potential ETc and precipitation totals are separate; incomplete-period totals remain null. `actual_water_balance` always remains null. This is not a model of field water sufficiency or an irrigation recommendation.

## Vercel deployment: two Projects, one repository

Do not deploy until the backend URL and environment variables have been reviewed.

1. Push the prepared repository to the intended GitHub repository manually.
2. In Vercel, import that repository as the backend project. Set **Root Directory** to `backend` and keep the detected FastAPI/Python settings. The Python version is pinned by `backend/.python-version` to 3.14. Vercel loads `app.py:app`; `backend/vercel.json` sets a 60-second function limit and excludes development-only assets. Set `ORBITFARM_RATE_LIMIT_PER_MINUTE` to a reviewed value (default 8 per minute per warm function instance). Copy the resulting HTTPS project URL.
3. Import the same GitHub repository again as a separate frontend project. Set **Root Directory** to `frontend` and use the Next.js preset/default build settings.
4. In the frontend project's Vercel environment variables, set `ORBITFARM_BACKEND_URL` to the backend HTTPS URL for Preview and Production. Do not prefix it with `NEXT_PUBLIC_`; do not use `localhost` or `127.0.0.1` for the deployed project. Redeploy the frontend after setting the variable.
5. Verify `/health`, `/api/crops`, a known `/api/nasa/assess` request through the frontend, and a backend-unavailable response before sharing the public URL.

The frontend proxy has a 55-second timeout and its route is configured for 60 seconds; the backend function is also configured for 60 seconds. NASA POWER calls have a 35-second timeout, and requests are limited to 366 historical days. Backend request bodies are capped at 500,000 bytes. Cache writes are best-effort; requests continue when the serverless filesystem is read-only. The in-memory NASA rate limiter is per function instance and is not a globally shared quota. Before substantial public traffic, configure Vercel Firewall/rate limiting or a shared external limiter; serverless filesystem state is not persistent.

## Rotation Planner API (custom-plan UI / v2 workflow)

The UI supports two editable plans and the original three demo sequences. The existing response contract intentionally keeps `schema_version=1.0.0` and `pipeline=orbitfarm_rotation_planner_v1`; the v2 custom-plan workflow does not rename API fields or statuses.

`POST /api/rotation/compare` returns three built-in three-season sequences. The request body may be `{}` or may include an optional compact `climate_context` copied from an existing NASA assessment:

```json
{
	"climate_context": {
		"historical_period": { "start": "2025-01-01", "end": "2025-03-31" },
		"location": { "latitude": 31.25, "longitude": 34.79 },
		"source_is_synthetic": false,
		"retrieved_from_cache": false,
		"observations": [
			{ "parameter_id": "CLIM_001", "value": 12.8, "unit": "°C" }
		]
	}
}
```

For user plans, add two or three entries. Each entry must have a unique `plan_id` and exactly three valid `crop_ids`:

```json
{
	"plans": [
		{ "plan_id": "custom_a", "crop_ids": ["wheat", "chickpea", "wheat"] },
		{ "plan_id": "custom_b", "crop_ids": ["wheat", "chickpea", "sorghum"] }
	],
	"climate_context": null
}
```

Omitting `plans` preserves the three demonstration sequences. `GET /api/rotation/options` returns all available crop IDs/names and the example plan definitions for clients.

Response `mode` is `descriptive_no_score`. Each plan distinguishes adjacent crop/family repetitions from returns after an intermediate season, reports `crop_group=legume`, distinct-crop count, catalogue advice matches, evidence, and limitations. Missing taxonomy is `unknown`. Botanical family labels are explicitly sourced as supplemental unverified taxonomy, and `ROT_001` advice is an unverified team draft. Historical climate context is never applied to future seasons; future climate fit always remains `unknown`. No yield, nitrogen, resilience, or overall rotation score is produced.

No deployment, GitHub push, or public repository creation has been performed by this workspace task.
