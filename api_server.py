"""Compatibility launcher for the canonical FastAPI app in backend/.

Run with backend/.venv's Python. No API implementation or data lives here.
"""
from pathlib import Path
import sys


if __name__ == "__main__":
    import uvicorn

    uvicorn.main(args=[
        "app:app", "--app-dir", str(Path(__file__).resolve().parent / "backend"),
        "--host", "127.0.0.1", "--port", "8000", *sys.argv[1:],
    ])
