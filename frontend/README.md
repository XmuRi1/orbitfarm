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
Copy-Item .env.example .env.local
```

Keep `ORBITFARM_BACKEND_URL` in `.env.local` set to the Python API origin. For local development use `http://127.0.0.1:8765`; in Vercel set it to the deployed backend URL. This value is only read by the Next.js server. Browser code calls `/api/assess`, never the Python API directly.

Start the backend from the repository root:

```powershell
py -3.15 backend/api_server.py
```

Then start the frontend from `frontend/`:

```powershell
npm run dev
```

Open http://localhost:3000.

## API route

`POST /api/assess` forwards the JSON request to `${ORBITFARM_BACKEND_URL}/api/nasa/assess` from the Next.js server. It passes through backend JSON and status codes, while reporting a missing backend configuration, connection failure, or invalid backend JSON separately.

## Result semantics

- NASA source, cache state, source URL, parameter units, aggregation windows, missing data, and warnings are shown from the actual response fields.
- `suitability_score_0_100` is displayed as unavailable when `null`.
- `demo_partial_score_0_100` is labeled as a demo-only partial score, separately from suitability.
- User-entered soil pH and texture are sent only when entered. They are not represented as NASA measurements.

## Map tiles

The interactive map uses the standard OpenStreetMap tile service with visible contributor attribution. It requests tiles for the map viewport only; the app does not prefetch areas or provide offline tile downloads. The initial center is a Beersheba-region test point, not the user's location, and browser geolocation is not requested. Tile availability is best-effort; see the [OpenStreetMap tile usage policy](https://operations.osmfoundation.org/policies/tiles/).

The assessment is exploratory. Crop requirements and demo weights are not scientifically validated, and the result is not a forecast or farming recommendation.
