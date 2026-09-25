"""容器健康检查：按 HEALTH_ROLE 检查 Web 或 API 端点。

用法：HEALTH_ROLE=web|api|both python scripts/healthcheck.py [base_url]
"""

from __future__ import annotations

import os
import sys
import urllib.request
import urllib.error

ROLE_PATHS = {
    "web": ["/health"],
    "api": ["/api/health"],
    "both": ["/health", "/api/health"],
}


def check(base_url: str, path: str) -> bool:
    url = base_url.rstrip("/") + path
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            ok = resp.status == 200
            body = resp.read(64)
            return ok and b"ok" in body
    except (urllib.error.URLError, OSError) as exc:
        print(f"healthcheck FAIL {url}: {exc}", file=sys.stderr)
        return False


def main() -> int:
    role = os.environ.get("HEALTH_ROLE", "both")
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    paths = ROLE_PATHS.get(role, ROLE_PATHS["both"])
    if all(check(base_url, path) for path in paths):
        print(f"healthcheck OK ({role})")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
