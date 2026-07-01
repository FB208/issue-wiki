from __future__ import annotations

import os
import sys
from pathlib import Path

import uvicorn


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
RUNTIME_ENV = ROOT / ".vscode" / ".runtime.env"


def main() -> None:
    sys.path.insert(0, str(BACKEND))
    load_runtime_env()
    port = int(os.environ.get("BACKEND_PORT", "8000"))
    uvicorn.run("app.main:app", host="127.0.0.1", port=port)


def load_runtime_env() -> None:
    if not RUNTIME_ENV.exists():
        return
    for raw_line in RUNTIME_ENV.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key.strip()] = value.strip()


if __name__ == "__main__":
    main()
