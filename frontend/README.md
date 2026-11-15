# OrbitFarm Frontend

Next.js App Router frontend for the OrbitFarm NASA POWER assessment API.

## Requirements

- Node.js 20.9 or newer
- npm
- The OrbitFarm Python API running separately

## Local setup

From this directory, install dependencies and configure the server-side backend URL:

```powershell
npm install
if (-not (Test-Path .env.local)) { Copy-Item .env.example .env.local }
```

Keep `ORBITFARM_BACKEND_URL` in `.env.local` set to the FastAPI origin. For local development use `http://127.0.0.1:8000`; in Vercel set it to the deployed backend URL. This value is only read by the Next.js server. Browser code calls relative Next.js routes, never the Python API directly. Restart Next.js after changing the variable.

Set up the backend venv and dependencies as described in the [root README](../README.md), then start FastAPI from the repository root:

```powershell
.\backend\.venv\Scripts\python.exe -m uvicorn app:app --app-dir backend --host 127.0.0.1 --port 8000 --reload
```

Then start the frontend from `frontend/`:

```powershell
npm run dev
```

Open http://localhost:3000.

## API route

`POST /api/assess` forwards the JSON request to `${ORBITFARM_BACKEND_URL}/api/nasa/assess` from the Next.js server. It passes through backend JSON and status codes, while reporting a missing backend configuration, connection failure, or invalid backend JSON separately.

`GET /api/rotation/options` and `POST /api/rotation/compare` forward to the same paths on FastAPI. The planner supports two user-defined three-season plans and the original three demo plans. Results remain descriptive with no rotation score; future climate suitability remains `unknown`. The legacy stdlib server on port 8765 does not support these routes.

Run `npm run lint`, `npx tsc --noEmit --incremental false`, and `npm run build` here. After building, run `backend/tests/smoke_local_stack.py` with the backend venv from the repository root for an HTTP test of the complete local stack; see the root README.

## Result semantics

- NASA source, cache state, source URL, parameter units, aggregation windows, missing data, and warnings are shown from the actual response fields.
- `suitability_score_0_100` is displayed as unavailable when `null`.
- `demo_partial_score_0_100` is labeled as a demo-only partial score, separately from suitability.
- User-entered soil pH and texture are sent only when entered. They are not represented as NASA measurements.

## Map tiles

The interactive map uses the standard OpenStreetMap tile service with visible contributor attribution. It requests tiles for the map viewport only; the app does not prefetch areas or provide offline tile downloads. The initial center is a Beersheba-region test point, not the user's location, and browser geolocation is not requested. Tile availability is best-effort; see the [OpenStreetMap tile usage policy](https://operations.osmfoundation.org/policies/tiles/).

The assessment is exploratory. Crop requirements and demo weights are not scientifically validated, and the result is not a forecast or farming recommendation.
