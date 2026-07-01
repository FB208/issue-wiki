from __future__ import annotations

import socket
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ENV = ROOT / ".vscode" / ".runtime.env"


def main() -> None:
    env = read_env(ROOT / ".env.example") | read_env(ROOT / ".env")
    backend_base = int(env.get("DEV_BACKEND_PORT", "8000"))
    frontend_base = int(env.get("DEV_FRONTEND_PORT", "5173"))

    backend_port = find_free_port(backend_base)
    frontend_port = find_free_port(frontend_base, reserved={backend_port})

    RUNTIME_ENV.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_ENV.write_text(
        "\n".join(
            [
                f"BACKEND_PORT={backend_port}",
                f"FRONTEND_PORT={frontend_port}",
                f"VITE_API_PROXY_TARGET=http://127.0.0.1:{backend_port}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"Backend port: {backend_port}")
    print(f"Frontend port: {frontend_port}")
    print(f"Runtime env: {RUNTIME_ENV}")


def read_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def find_free_port(start: int, reserved: set[int] | None = None) -> int:
    reserved = reserved or set()
    port = start
    while port in reserved or not is_free(port):
        port += 1
    return port


def is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


if __name__ == "__main__":
    main()
