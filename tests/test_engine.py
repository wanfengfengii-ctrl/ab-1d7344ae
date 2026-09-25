"""归因引擎单元测试。"""

from __future__ import annotations

import pytest

from app.engine import (
    ValidationError,
    build_network,
    build_rounds,
    diagnose,
    reachable_nodes,
    serialize_result,
)


# ---------------------------------------------------------------- 基础工具


def payload_5_6():
    """最小合法骨架：5 节点 6 电缆 2 轮，全部通电。"""
    nodes = ["S", "A", "B", "C", "D"]
    return {
        "nodes": nodes,
        "source": "S",
        "cables": [
            {"a": "S", "b": "A", "risk": 1},
            {"a": "A", "b": "B", "risk": 1},
            {"a": "B", "b": "C", "risk": 1},
            {"a": "C", "b": "D", "risk": 1},
            {"a": "D", "b": "S", "risk": 1},
            {"a": "S", "b": "C", "risk": 1},
        ],
        "rounds": [
            {"closed": [1, 2, 3, 4, 5, 6],
             "readings": {n: True for n in nodes}},
            {"closed": [1, 2, 3, 4, 5, 6],
             "readings": {n: True for n in nodes}},
        ],
    }


def test_reachable_basic_and_source_always_on():
    net = build_network(payload_5_6())
    # 电缆全部导通：全部可达
    assert reachable_nodes(net, frozenset(), frozenset(range(1, 7))) == set(net.nodes)
    # 无闭合电缆：仅电源可达
    assert reachable_nodes(net, frozenset(), frozenset()) == {"S"}
    # 电源节点即使无任何边也可达自己
    assert "S" in reachable_nodes(net, frozenset([1, 2, 3, 4, 5, 6]), frozenset())


def test_failed_and_closed_interaction():
    # 故障电缆即使在闭合集合中也不导通
    net = build_network(payload_5_6())
    reach = reachable_nodes(net, frozenset([6]), frozenset(range(1, 7)))
    # 环网仍有替代通路
    assert reach == set(net.nodes)
    reach2 = reachable_nodes(net, frozenset([1, 5]), frozenset(range(1, 7)))
    # 去掉 S-A(1) 与 D-S(5)：A-B-C-D 经 #6 S-C 仍全部可达
    assert reach2 == set(net.nodes)


# ---------------------------------------------------------------- 校验


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p["nodes"].pop(),
        lambda p: p.update(nodes=[f"N{i}" for i in range(11)]),
        lambda p: p["cables"].pop(),
        lambda p: p.update(cables=p["cables"] + [p["cables"][-1]] * 9),
        lambda p: p["rounds"].pop(),
        lambda p: p.update(rounds=p["rounds"] * 4),
    ],
)
def test_count_limits_enforced(mutate):
    p = payload_5_6()
    mutate(p)
    with pytest.raises(ValidationError):
        diagnose(p)


def test_source_must_be_node_and_readings_complete():
    p = payload_5_6()
    p["source"] = "X"
    with pytest.raises(ValidationError):
        diagnose(p)

    p = payload_5_6()
    del p["rounds"][0]["readings"]["D"]
    # 引擎默认允许部分节点无读数；业务完整模式必须拒绝
    net = build_network(p)
    with pytest.raises(ValidationError):
        build_rounds(net, p, complete=True)


def test_negative_risk_rejected():
    p = payload_5_6()
    p["cables"][0]["risk"] = -2
    with pytest.raises(ValidationError):
        diagnose(p)


# ---------------------------------------------------------------- 归因主流程


def test_ring_multiround_locates_broken_cable():
    """环网场景：#4(B-C) 永久失效，单轮无法识别，多轮联合唯一指向 #4。"""
    nodes = ["P", "A", "B", "C", "D"]
    p = {
        "nodes": nodes,
        "source": "P",
        "cables": [
            {"a": "P", "b": "A", "risk": 5},   # 1
            {"a": "P", "b": "B", "risk": 9},   # 2
            {"a": "A", "b": "B", "risk": 2},   # 3
            {"a": "B", "b": "C", "risk": 3},   # 4 长期失效
            {"a": "C", "b": "D", "risk": 4},   # 5
            {"a": "A", "b": "D", "risk": 6},   # 6
        ],
        "rounds": [
            # 全部闭合：环网替代通路使所有传感器仍通电（漏判陷阱）
            {"closed": [1, 2, 3, 4, 5, 6],
             "readings": dict.fromkeys(nodes, True)},
            {"closed": [1, 3, 4, 5],
             "readings": {"P": True, "A": True, "B": True, "C": False, "D": False}},
            {"closed": [2, 4, 6],
             "readings": {"P": True, "A": False, "B": True, "C": False, "D": False}},
        ],
    }
    result = diagnose(p)
    assert result.feasible
    assert result.explanation.failed == (4,)
    assert result.explanation.total_risk == 3
    # 第 1 轮全部通电、第 2/3 轮部分断电均吻合
    assert all(rr.matched for rr in result.explanation.rounds)
    r2 = result.explanation.rounds[1]
    assert set(r2.reachable) == {"P", "A", "B"}


def test_no_failure_when_network_healthy():
    p = payload_5_6()
    result = diagnose(p)
    assert result.feasible
    assert result.explanation.failed == ()
    assert result.explanation.total_risk == 0


def test_infeasible_when_source_reported_off():
    p = payload_5_6()
    p["rounds"][0]["readings"]["S"] = False
    result = diagnose(p)
    assert not result.feasible
    assert result.explanation is None


def test_infeasible_conflicting_rounds():
    # 同一闭合配置下两轮给出互相矛盾的读数
    p = payload_5_6()
    p["rounds"] = [
        {"closed": [1, 2, 3, 4, 5, 6],
         "readings": {n: True for n in p["nodes"]}},
        {"closed": [1, 2, 3, 4, 5, 6],
         "readings": {**{n: True for n in p["nodes"]}, "D": False}},
    ]
    result = diagnose(p)
    assert not result.feasible
    body = serialize_result(build_network(p), result)
    assert "不能由同一组永久故障" in body["message"]


def test_all_combinations_evaluated():
    p = payload_5_6()
    result = diagnose(p)
    assert result.candidates_evaluated == 2 ** 6


# ---------------------------------------------------------------- 择优规则


def diamond_payload(risks):
    """菱形双通路 S-X-A（#1,#2）与 S-Y-A（#3,#4）；
    闭合四条边而读数 A 断电 ⇒ 故障集合必须是一个规模 2 的 S–A 割集。
    只给 S/A 读数（X/Y 不约束），故四个交叉割集
    {1,3}/{1,4}/{2,3}/{2,4} 全部可行，用于检验三级择优。
    另加节点 B 与电缆 #5/#6（各轮均不闭合）满足规模约束。"""
    nodes = ["S", "X", "Y", "A", "B"]
    on = {"S": True, "A": False}
    round_ = {"closed": [1, 2, 3, 4], "readings": on}
    return {
        "nodes": nodes,
        "source": "S",
        "cables": [
            {"a": "S", "b": "X", "risk": risks[0]},
            {"a": "X", "b": "A", "risk": risks[1]},
            {"a": "S", "b": "Y", "risk": risks[2]},
            {"a": "Y", "b": "A", "risk": risks[3]},
            {"a": "S", "b": "B", "risk": 1},
            {"a": "B", "b": "A", "risk": 1},
        ],
        "rounds": [dict(round_), dict(round_)],
    }


def test_tie_break_by_entry_order_bit_sequence():
    # 四个规模 2 的割集 {1,3}/{1,4}/{2,3}/{2,4}，风险全相同，
    # 取录入序列字典序最小：0101 即 {2,4}
    p = diamond_payload([1, 1, 1, 1])
    result = diagnose(p)
    assert result.feasible
    assert result.explanation.failed == (2, 4)
    assert result.explanation.total_risk == 2


def test_tie_break_by_total_risk_before_sequence():
    # {1,4} 风险和最低（1+1），即使序列 1001 大于 0101 也优先
    p = diamond_payload([1, 100, 100, 1])
    result = diagnose(p)
    assert result.feasible
    assert result.explanation.failed == (1, 4)
    assert result.explanation.total_risk == 2


def test_fewer_failures_has_priority_over_risk():
    # 规模 2 的解释（风险和 2）必须胜过任何规模 3 的组合（风险和 ≥3）
    p = diamond_payload([1, 1, 1, 1])
    p["rounds"][1] = {
        "closed": [1, 2, 3],
        "readings": {"S": True, "A": False},
    }
    result = diagnose(p)
    assert result.feasible
    assert len(result.explanation.failed) == 2
    assert result.explanation.failed == (2, 4)
