# OrbitFarm

NASA POWER climate assessment prototype with a Next.js frontend and Python backend. The crop scoring model and requirements remain exploratory and are not an agronomic recommendation.

## Repository layout

```text
backend/   Python scoring, NASA POWER adapter, local HTTP API, FastAPI ASGI app, data and tests
frontend/  Next.js App Router, interactive Leaflet map, server-side API proxy
```

Generated NASA caches, assessment outputs, Python bytecode, virtual environments, node_modules, Next build files, and environment files are excluded by the root `.gitignore`. Only `.env.example` files are intended for version control; never put tokens or credentials in them.

## Local development

Requirements: Python 3.12+ (Python 3.15 works locally), Node.js 20.9+, and npm.

Start the existing stdlib API from the repository root:

```powershell
py -3.15 backend/api_server.py
```

In another terminal, configure and start the frontend:

```powershell
cd frontend
npm ci
Copy-Item .env.example .env.local
```

Set `ORBITFARM_BACKEND_URL=http://127.0.0.1:8765` in `frontend/.env.local`, then run:

```powershell
npm run dev
```

Open http://127.0.0.1:3000. The browser only calls the relative Next route `/api/assess`; the Next server forwards it to the Python API. The frontend environment variable is server-only.

To run the FastAPI ASGI entrypoint locally instead of the stdlib API:

```powershell
cd backend
py -3.15 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-local.txt
.\.venv\Scripts\python -m uvicorn app:app --reload --port 8000
```

Use `ORBITFARM_BACKEND_URL=http://127.0.0.1:8000` with this option.

## Verification

From the repository root:

```powershell
py -3.15 -m unittest discover -s backend/tests -v
cd frontend
npm ci
npm run lint
npx tsc --noEmit
npm run build
```

ASGI-specific tests use `backend/requirements-test.txt`; install that file in a virtual environment before running the full Python suite:

```powershell
cd backend
py -3.15 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-test.txt
cd ..
backend\.venv\Scripts\python -m unittest discover -s backend/tests -v
```

## Vercel deployment: two Projects, one repository

Do not deploy until the backend URL and environment variables have been reviewed.

1. Push the prepared repository to the intended GitHub repository manually.
2. In Vercel, import that repository as the backend project. Set **Root Directory** to `backend` and keep the detected FastAPI/Python settings. The Python version is pinned by `backend/.python-version` to 3.14. Vercel loads `app.py:app`; `backend/vercel.json` sets a 60-second function limit and excludes development-only assets. Set `ORBITFARM_RATE_LIMIT_PER_MINUTE` to a reviewed value (default 8 per minute per warm function instance). Copy the resulting HTTPS project URL.
3. Import the same GitHub repository again as a separate frontend project. Set **Root Directory** to `frontend` and use the Next.js preset/default build settings.
4. In the frontend project's Vercel environment variables, set `ORBITFARM_BACKEND_URL` to the backend HTTPS URL for Preview and Production. Do not prefix it with `NEXT_PUBLIC_`; do not use `localhost` or `127.0.0.1` for the deployed project. Redeploy the frontend after setting the variable.
5. Verify `/health`, `/api/crops`, a known `/api/nasa/assess` request through the frontend, and a backend-unavailable response before sharing the public URL.

The frontend proxy has a 55-second timeout and its route is configured for 60 seconds; the backend function is also configured for 60 seconds. NASA POWER calls have a 35-second timeout, and requests are limited to 366 historical days. Backend request bodies are capped at 500,000 bytes. Cache writes are best-effort; requests continue when the serverless filesystem is read-only. The in-memory NASA rate limiter is per function instance and is not a globally shared quota. Before substantial public traffic, configure Vercel Firewall/rate limiting or a shared external limiter; serverless filesystem state is not persistent.

No deployment, GitHub push, or public repository creation has been performed by this workspace task.
