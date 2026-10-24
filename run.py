"""Dev runner: `uv run python run.py` serves the API on port 8000 with reload.

DATA_DIR defaults to ./data. Production runs uvicorn directly (one worker; see the Dockerfile).
"""

import os

import uvicorn

if __name__ == "__main__":
    os.environ.setdefault("DATA_DIR", "./data")
    trust_proxy = os.environ.get("TRUST_PROXY") == "1"
    uvicorn.run(
        "backend.main:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        reload=True,
        reload_dirs=["backend"],
        proxy_headers=trust_proxy,
        forwarded_allow_ips="*" if trust_proxy else None,
    )
