"""一次性验收脚本：代码测试 + 启动服务 + API 业务冒烟，退出码报告验收结果。

在 verify 容器内执行：
  1. 运行全部 pytest 代码测试；
  2. 本地拉起 uvicorn 服务，等待 Web/API 健康检查通过；
  3. 通过真实 HTTP 执行业务冒烟（可行归因 + 无共同解释两种场景）；
  4. 关闭服务，以 0/非 0 退出码报告验收结论。
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOST = "127.0.0.1"
PORT = int(os.environ.get("VERIFY_PORT", "8011"))
BASE = f"http://{HOST}:{PORT}"

failures: list[str] = []


def record(ok: bool, label: str, detail: str = "") -> None:
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def request(method: str, path: str, payload: dict | None = None, timeout: int = 10):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        # 4xx 同样读取 JSON 响应体（如 422 校验错误）
        return exc.code, json.loads(exc.read().decode())


def wait_for_port(host: str, port: int, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex((host, port)) == 0:
                return True
        time.sleep(0.3)
    return False


def wait_healthy(path: str, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            status, body = request("GET", path)
            if status == 200 and body.get("status") == "ok":
                return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.4)
    return False


def ring_payload() -> dict:
    nodes = ["P", "A", "B", "C", "D"]
    return {
        "name": "验收冒烟-环网",
        "nodes": nodes,
        "source": "P",
        "cables": [
            {"a": "P", "b": "A", "risk": 5},
            {"a": "P", "b": "B", "risk": 9},
            {"a": "A", "b": "B", "risk": 2},
            {"a": "B", "b": "C", "risk": 3},
            {"a": "C", "b": "D", "risk": 4},
            {"a": "A", "b": "D", "risk": 6},
        ],
        "rounds": [
            {"closed": [1, 2, 3, 4, 5, 6],
             "readings": {n: True for n in nodes}},
            {"closed": [1, 3, 4, 5],
             "readings": {"P": True, "A": True, "B": True, "C": False, "D": False}},
            {"closed": [2, 4, 6],
             "readings": {"P": True, "A": False, "B": True, "C": False, "D": False}},
        ],
    }


def smoke() -> None:
    print("\n== 健康检查 ==")
    record(wait_healthy("/health"), "Web 健康检查 GET /health")
    record(wait_healthy("/api/health"), "API 健康检查 GET /api/health")

    print("\n== 业务冒烟：可行归因（#4 长期失效）==")
    status, body = request("POST", "/api/diagnose", ring_payload())
    record(status == 200 and body.get("feasible") is True,
           "归因接口返回可行解释", f"http {status}")
    exp = (body.get("explanation") or {})
    record(exp.get("failed_cables") == [4],
           "故障电缆编号为 #4", str(exp.get("failed_cables")))
    record(exp.get("total_risk") == 3,
           "修复风险和为 3", str(exp.get("total_risk")))
    rounds = exp.get("rounds") or []
    record(len(rounds) == 3 and all(r.get("matched") for r in rounds),
           "3 轮读数比对全部吻合")
    r2 = rounds[1] if len(rounds) > 1 else {}
    record(r2.get("reachable_sensors") == ["P", "A", "B"],
           "第 2 轮可达传感器为 P、A、B",
           str(r2.get("reachable_sensors")))

    print("\n== 业务冒烟：无共同解释 ==")
    bad = ring_payload()
    bad["rounds"][0]["readings"]["P"] = False  # 电源断电，不可能成立
    status, body = request("POST", "/api/diagnose", bad)
    record(status == 200 and body.get("feasible") is False,
           "矛盾读数被判定为不可解释", f"http {status}")
    record("不能由同一组永久故障" in (body.get("message") or ""),
           "返回明确的无共同解释提示", str(body.get("message")))

    print("\n== 业务冒烟：录入校验 ==")
    invalid = ring_payload()
    invalid["nodes"] = ["P", "A"]
    status, body = request("POST", "/api/diagnose", invalid)
    record(status == 422 and "节点数量" in body.get("detail", ""),
           "非法草稿返回 422 与中文原因", f"http {status}")


def main() -> int:
    print("== 1/3 代码测试（pytest） ==")
    test_proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=ROOT,
    )
    record(test_proc.returncode == 0, "pytest 全部代码测试通过",
           f"exit={test_proc.returncode}")
    if test_proc.returncode != 0:
        print("\n验收结果：FAIL（代码测试未通过，跳过 API 冒烟）")
        return 1

    print("\n== 2/3 启动服务 ==")
    log_path = os.path.join(ROOT, ".verify-uvicorn.log")
    log_file = open(log_path, "w", encoding="utf-8")
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", HOST, "--port", str(PORT)],
        cwd=ROOT,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        record(wait_for_port(HOST, PORT), f"服务在 {BASE} 监听")
        print("\n== 3/3 API 业务冒烟 ==")
        smoke()
    finally:
        server.terminate()
        try:
            server.wait(timeout=8)
        except subprocess.TimeoutExpired:
            server.kill()
        log_file.close()

    if failures:
        print(f"\n验收结果：FAIL（{len(failures)} 项未通过：{failures}）")
        return 1
    print("\n验收结果：PASS（构建产物、代码测试、API 业务冒烟全部通过）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
