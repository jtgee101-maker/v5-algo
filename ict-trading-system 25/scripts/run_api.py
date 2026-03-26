"""Start the FastAPI backend server.

Usage:
  python scripts/run_api.py
  python scripts/run_api.py --port 8080
"""

import argparse
import uvicorn

from backend.settings import API_HOST, API_PORT, API_RELOAD


def main():
    parser = argparse.ArgumentParser(description="ICT Trading System API")
    parser.add_argument("--host", default=API_HOST)
    parser.add_argument("--port", type=int, default=API_PORT)
    parser.add_argument("--no-reload", action="store_true")
    args = parser.parse_args()

    print("=" * 60)
    print("ICT Trade Mission Control — API Server")
    print(f"  http://{args.host}:{args.port}")
    print(f"  Docs: http://{args.host}:{args.port}/docs")
    print("=" * 60)

    uvicorn.run(
        "backend.app:app",
        host=args.host,
        port=args.port,
        reload=not args.no_reload,
    )


if __name__ == "__main__":
    main()
