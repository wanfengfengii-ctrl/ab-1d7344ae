"""归因引擎：在永久故障电缆组合中逐轮计算电源可达性。

规则概述
--------
* 网络由若干节点（含唯一电源节点）与无向电缆组成，电缆按录入顺序从 1 编号。
* 一组"永久故障"电缆在所有试验轮次中都保持断开。
* 每一轮还会记录该轮闭合（投入）的电缆：某条电缆在某一轮导通，
  当且仅当它没有永久故障 **且** 在该轮闭合集合中。
* 传感器（节点）通电，当且仅当在该轮实际导通的子图中它与电源节点连通；
  电源节点自身恒为通电。

只有一组故障组合在所有轮次推导出的通电/断电读数与录入读数完全吻合时，
才可作为候选解释。最终在全部候选中依次按以下标准择优：

1. 故障电缆数量最少；
2. 故障电缆修复风险总和最低；
3. 按电缆录入顺序展开的 0/1 故障编号序列字典序最小
   （等价于：最早录入的电缆尽量不断）。
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import fsum
from typing import Iterable


class ValidationError(ValueError):
    """录入草稿不满足业务约束时抛出。"""


@dataclass(frozen=True)
class Cable:
    a: str
    b: str
    risk: float


@dataclass(frozen=True)
class Round:
    closed: frozenset[int]  # 1-based 电缆编号
    readings: dict[str, bool]  # 节点 -> True 通电 / False 断电


@dataclass(frozen=True)
class Network:
    nodes: tuple[str, ...]
    source: str
    cables: tuple[Cable, ...]

    @property
    def n_cables(self) -> int:
        return len(self.cables)


@dataclass(frozen=True)
class RoundResult:
    round_index: int  # 0-based
    closed: tuple[int, ...]  # 1-based，按录入顺序
    reachable: tuple[str, ...]  # 可达（通电）节点，按录入顺序
    readings: tuple[tuple[str, bool, bool], ...]  # (节点, 期望, 实际)
    matched: bool


@dataclass(frozen=True)
class Explanation:
    failed: tuple[int, ...]  # 1-based 电缆编号
    risks: tuple[float, ...]
    total_risk: float
    rounds: tuple[RoundResult, ...]


@dataclass(frozen=True)
class DiagnosisResult:
    feasible: bool
    explanation: Explanation | None
    candidates_evaluated: int


# ---------------------------------------------------------------------------
# 校验与建模
# ---------------------------------------------------------------------------

def _is_number(value: object) -> bool:
    # bool 是 int 的子类，风险不接受布尔值
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def build_network(payload: dict) -> Network:
    """从前端提交的草稿 dict 构建并校验网络。"""
    raw_nodes = payload.get("nodes")
    source = payload.get("source")
    raw_cables = payload.get("cables")

    if not isinstance(raw_nodes, list) or not all(isinstance(n, str) for n in raw_nodes):
        raise ValidationError("节点必须为字符串列表")
    nodes = [n.strip() for n in raw_nodes]
    if any(n == "" for n in nodes):
        raise ValidationError("节点名称不能为空")
    if len(nodes) != len(set(nodes)):
        raise ValidationError("节点名称必须唯一")
    if not 5 <= len(nodes) <= 10:
        raise ValidationError("节点数量必须在 5 至 10 个之间")

    if not isinstance(source, str) or source.strip() not in nodes:
        raise ValidationError("电源节点必须是已录入节点之一")
    source = source.strip()
    nodes = [n.strip() for n in nodes]

    if not isinstance(raw_cables, list) or not 6 <= len(raw_cables) <= 14:
        raise ValidationError("电缆数量必须在 6 至 14 条之间")

    node_set = set(nodes)
    cables: list[Cable] = []
    for i, c in enumerate(raw_cables):
        if not isinstance(c, dict):
            raise ValidationError(f"第 {i + 1} 条电缆格式不正确")
        a, b = c.get("a"), c.get("b")
        risk = c.get("risk", 1)
        if not isinstance(a, str) or not isinstance(b, str):
            raise ValidationError(f"第 {i + 1} 条电缆的两端必须是节点名")
        a, b = a.strip(), b.strip()
        if a not in node_set or b not in node_set:
            raise ValidationError(f"第 {i + 1} 条电缆引用了不存在的节点")
        if a == b:
            raise ValidationError(f"第 {i + 1} 条电缆不能是自环")
        if not _is_number(risk) or risk < 0:
            raise ValidationError(f"第 {i + 1} 条电缆的修复风险必须是非负数字")
        cables.append(Cable(a=a, b=b, risk=float(risk)))

    return Network(nodes=tuple(nodes), source=source, cables=tuple(cables))


def build_rounds(network: Network, payload: dict, *, complete: bool = False) -> list[Round]:
    """解析试验轮次。

    引擎层面允许只给部分节点读数（未给读数的节点不参与比对，视为内部节点）；
    API 业务校验通过 ``complete=True`` 要求每个传感器（节点）都有读数。
    """
    raw_rounds = payload.get("rounds")
    if not isinstance(raw_rounds, list) or not 2 <= len(raw_rounds) <= 7:
        raise ValidationError("试验轮次必须在 2 至 7 轮之间")

    rounds: list[Round] = []
    node_set = set(network.nodes)
    for r, raw in enumerate(raw_rounds):
        if not isinstance(raw, dict):
            raise ValidationError(f"第 {r + 1} 轮数据格式不正确")
        raw_closed = raw.get("closed", [])
        raw_readings = raw.get("readings", {})

        if not isinstance(raw_closed, list) or not all(
            isinstance(x, int) and not isinstance(x, bool) for x in raw_closed
        ):
            raise ValidationError(f"第 {r + 1} 轮闭合电缆必须是编号列表")
        closed = frozenset(int(x) for x in raw_closed)
        bad = [x for x in closed if not 1 <= x <= network.n_cables]
        if bad:
            raise ValidationError(
                f"第 {r + 1} 轮存在越界电缆编号：{sorted(bad)}"
            )

        if not isinstance(raw_readings, dict):
            raise ValidationError(f"第 {r + 1} 轮读数必须是节点到通断状态的映射")
        extra = set(raw_readings.keys()) - node_set
        if extra:
            raise ValidationError(
                f"第 {r + 1} 轮读数引用了不存在的节点：{sorted(extra)}"
            )
        if complete:
            missing = node_set - set(raw_readings.keys())
            if missing:
                raise ValidationError(
                    f"第 {r + 1} 轮缺少传感器读数：{sorted(missing)}"
                )
        readings: dict[str, bool] = {}
        for node, on in raw_readings.items():
            if not isinstance(on, bool):
                raise ValidationError(f"第 {r + 1} 轮 {node} 的读数必须是通电/断电布尔值")
            readings[node] = on

        rounds.append(Round(closed=closed, readings=readings))
    return rounds


# ---------------------------------------------------------------------------
# 可达性与归因
# ---------------------------------------------------------------------------

def reachable_nodes(
    network: Network, failed: frozenset[int], closed: frozenset[int]
) -> frozenset[str]:
    """计算给定永久故障集合与本轮闭合集合下，电源可达的节点集合。

    电缆编号为 1-based。导通条件：未永久故障 且 本轮闭合。
    """
    adjacency: dict[str, list[str]] = {n: [] for n in network.nodes}
    for idx, cable in enumerate(network.cables, start=1):
        if idx in failed or idx not in closed:
            continue
        adjacency[cable.a].append(cable.b)
        adjacency[cable.b].append(cable.a)

    seen = {network.source}
    stack = [network.source]
    while stack:
        cur = stack.pop()
        for nxt in adjacency[cur]:
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return frozenset(seen)


def _bit_signature(network: Network, failed: frozenset[int]) -> tuple[int, ...]:
    """按电缆录入顺序展开的故障 0/1 序列（1 表示故障）。"""
    return tuple(1 if i in failed else 0 for i in range(1, network.n_cables + 1))


def _simulate_rounds(
    network: Network, rounds: list[Round], failed: frozenset[int]
) -> tuple[bool, tuple[RoundResult, ...]]:
    results: list[RoundResult] = []
    all_matched = True
    for r, rnd in enumerate(rounds):
        reach = reachable_nodes(network, failed, rnd.closed)
        rows: list[tuple[str, bool, bool]] = []
        matched = True
        for node in network.nodes:
            actual = node in reach
            expected = rnd.readings.get(node, actual)  # 未录入读数的节点不参与比对
            rows.append((node, expected, actual))
            if expected != actual:
                matched = False
        if not matched:
            all_matched = False
        results.append(
            RoundResult(
                round_index=r,
                closed=tuple(sorted(rnd.closed)),
                reachable=tuple(n for n in network.nodes if n in reach),
                readings=tuple(rows),
                matched=matched,
            )
        )
    return all_matched, tuple(results)


def _iter_failed_sets(n: int) -> Iterable[frozenset[int]]:
    """按 (故障数升序, 录入序列字典序升序) 枚举所有电缆子集。"""
    for size in range(n + 1):
        for comb in combinations(range(1, n + 1), size):
            yield frozenset(comb)


def diagnose(payload: dict, *, complete: bool = False) -> DiagnosisResult:
    """在所有永久故障组合中寻找与全部轮次读数吻合的最优解释。"""
    network = build_network(payload)
    rounds = build_rounds(network, payload, complete=complete)

    best: Explanation | None = None
    best_key: tuple[int, float, tuple[int, ...]] | None = None
    evaluated = 0

    for failed in _iter_failed_sets(n=network.n_cables):
        evaluated += 1
        matched, round_results = _simulate_rounds(network, rounds, failed)
        if not matched:
            continue
        sig = _bit_signature(network, failed)
        total_risk = fsum(
            network.cables[i - 1].risk for i in failed
        )
        key = (len(failed), total_risk, sig)
        if best_key is None or key < best_key:
            best_key = key
            best = Explanation(
                failed=tuple(sorted(failed)),
                risks=tuple(network.cables[i - 1].risk for i in sorted(failed)),
                total_risk=total_risk,
                rounds=round_results,
            )

    return DiagnosisResult(feasible=best is not None, explanation=best,
                           candidates_evaluated=evaluated)


def serialize_result(network: Network, result: DiagnosisResult) -> dict:
    """把归因结果转为 API 响应 JSON。"""
    if not result.feasible or result.explanation is None:
        return {
            "feasible": False,
            "message": "这些试验读数不能由同一组永久故障同时解释。",
            "candidates_evaluated": result.candidates_evaluated,
            "explanation": None,
        }
    exp = result.explanation
    cables_out = [
        {
            "index": i,
            "a": network.cables[i - 1].a,
            "b": network.cables[i - 1].b,
            "risk": network.cables[i - 1].risk,
            "failed": i in exp.failed,
        }
        for i in range(1, network.n_cables + 1)
    ]
    return {
        "feasible": True,
        "message": None,
        "candidates_evaluated": result.candidates_evaluated,
        "explanation": {
            "failed_cables": list(exp.failed),
            "failed_count": len(exp.failed),
            "total_risk": exp.total_risk,
            "cables": cables_out,
            "rounds": [
                {
                    "round_index": rr.round_index,
                    "closed": list(rr.closed),
                    "reachable_sensors": list(rr.reachable),
                    "matched": rr.matched,
                    "readings": [
                        {"node": node, "expected": exp_on, "actual": act_on,
                         "match": exp_on == act_on}
                        for node, exp_on, act_on in rr.readings
                    ],
                }
                for rr in exp.rounds
            ],
        },
    }
