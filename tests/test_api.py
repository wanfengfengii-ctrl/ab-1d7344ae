"""API 层测试：健康检查、业务归因、校验错误与无共同解释。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def ring_payload():
    nodes = ["P", "A", "B", "C", "D"]
    return {
        "name": "环网测试",
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


def test_health_endpoints():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    r2 = client.get("/health")
    assert r2.status_code == 200
    assert r2.json()["service"] == "web"


def test_index_page_served():
    r = client.get("/")
    assert r.status_code == 200
    assert "永久故障" in r.text
    r_css = client.get("/static/app.js")
    assert r_css.status_code == 200


def test_diagnose_success_payload_shape():
    r = client.post("/api/diagnose", json=ring_payload())
    assert r.status_code == 200
    data = r.json()
    assert data["feasible"] is True
    assert data["name"] == "环网测试"
    exp = data["explanation"]
    assert exp["failed_cables"] == [4]
    assert exp["failed_count"] == 1
    assert exp["total_risk"] == 3
    assert len(exp["rounds"]) == 3
    # 每轮都带可达传感器与逐点读数比对
    r2 = exp["rounds"][1]
    assert r2["reachable_sensors"] == ["P", "A", "B"]
    assert r2["matched"] is True
    assert {row["node"] for row in r2["readings"]} == {"P", "A", "B", "C", "D"}
    assert all(row["match"] for row in r2["readings"])


def test_diagnose_infeasible_message():
    p = ring_payload()
    p["rounds"][0]["readings"]["P"] = False  # 电源不可能断电
    r = client.post("/api/diagnose", json=p)
    assert r.status_code == 200
    data = r.json()
    assert data["feasible"] is False
    assert data["explanation"] is None
    assert "不能由同一组永久故障" in data["message"]


def test_validation_missing_readings_returns_422():
    p = ring_payload()
    del p["rounds"][0]["readings"]["C"]
    r = client.post("/api/diagnose", json=p)
    assert r.status_code == 422
    assert "缺少传感器读数" in r.json()["detail"]


def test_validation_bad_counts_returns_422():
    p = ring_payload()
    p["nodes"] = ["P", "A"]  # 少于 5 个
    r = client.post("/api/diagnose", json=p)
    assert r.status_code == 422
    assert "节点数量" in r.json()["detail"]


def test_validation_unknown_source_returns_422():
    p = ring_payload()
    p["source"] = "Z"
    r = client.post("/api/diagnose", json=p)
    assert r.status_code == 422


def test_validation_duplicate_closed_ids_ok_and_negative_risk_rejected():
    p = ring_payload()
    p["rounds"][0]["closed"] = [1, 1, 2, 3, 4, 5, 6]  # 重复编号等价于闭合
    r = client.post("/api/diagnose", json=p)
    assert r.status_code == 200

    p2 = ring_payload()
    p2["cables"][0]["risk"] = -1
    r2 = client.post("/api/diagnose", json=p2)
    assert r2.status_code == 422
