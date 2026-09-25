# 深海观测网 · 永久故障电缆归因系统

深海观测环网完成维护后，工程师依据**多轮**继电器切换下各传感器的通电/断电读数，
联合推断长期失效（永久故障）的海底电缆，避免按单轮读数局部判断而遗漏环网替代通路。

本服务在所有永久故障电缆组合中**逐轮**计算电源可达性，只有与全部轮次读数均吻合的
组合才可采用，并依次按以下标准择优：

1. **故障电缆数量最少**；
2. **修复风险总和最低**；
3. **按电缆录入顺序展开的故障编号序列（0/1）字典序最小**（最早录入的电缆尽量不断）。

若不存在任何能同时解释所有轮次读数的永久故障组合，系统明确回复
"这些试验读数不能由同一组永久故障同时解释"。页面在草稿被修改后立即作废旧结论，
只有重新发起归因才会展示新结论。

## 业务模型

* 录入 5–10 个节点（含**唯一**电源节点）、6–14 条带非负修复风险的无向电缆
  （电缆按录入顺序从 1 编号），以及 2–7 轮试验。
* 每轮记录：该轮**闭合（投入）**的电缆集合、每个传感器的通电/断电读数。
* 一条电缆在某一轮导通，当且仅当：它没有永久故障 **且** 在该轮闭合集合中。
* 传感器通电 ⇔ 该轮导通子图中与电源连通（电源自身恒通电）。
* 枚举全部 2^m 个故障组合（m ≤ 14，故至多 16384 组），逐轮做连通性仿真并与读数
  逐点比对；在全部吻合的候选中按上述三级标准选出唯一最优结论。

## 目录结构

```
app/
  engine.py          归因引擎：校验、可达性、穷举与三级择优、结果序列化
  main.py            FastAPI：Web 页面 + 业务 API（/api/diagnose、健康检查）
  static/            原生 HTML/CSS/JS 前端（无构建依赖）
tests/               pytest 单元与接口测试
scripts/
  healthcheck.py     容器双角色健康检查（web / api）
  verify.py          一次性验收：pytest + 起服 + API 业务冒烟
Dockerfile           单镜像（含测试与验收脚本）
docker-compose.yml   web / api / verify 三个服务
```

## 本地运行

```bash
python3 -m venv .venv && . .venv/bin/
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
# 浏览器打开 http://localhost:8000
```

## Docker Compose

```bash
# 启动 Web（/health）与 API（/api/health），均带健康检查
docker compose up -d --build
# 页面：http://localhost:8080    API：http://localhost:8000
```

### 配置宿主机端口

通过环境变量或 `.env`（参见 `.env.example`）：

```bash
WEB_HOST_PORT=18080 API_HOST_PORT=18000 docker compose up -d --build
```

### 一次性验收服务 verify

`verify` 服务完成 **镜像构建 → 代码测试 → 启动服务 → API 业务冒烟** 后自行退出，
并以容器退出码报告验收结果（0 通过 / 非 0 失败）：

```bash
docker compose up --build verify
# 查看退出码：
docker compose ps verify            # STATUS 为 Exited (0)
docker inspect --format '{{.State.ExitCode}}' $(docker compose ps -q verify)
```

冒烟覆盖：Web/API 健康检查、可行归因（故障 #4、风险和、逐轮可达传感器与读数比对）、
无共同解释（电源被录为断电）、非法草稿 422。

## HTTP API

### `GET /api/health` / `GET /health`

```json
{"status": "ok", "service": "api"}
```

### `POST /api/diagnose`

请求：

```json
{
  "name": "南海三号环网",
  "nodes": ["P", "A", "B", "C", "D"],
  "source": "P",
  "cables": [
    {"a": "P", "b": "A", "risk": 5},
    {"a": "P", "b": "B", "risk": 9},
    {"a": "A", "b": "B", "risk": 2},
    {"a": "B", "b": "C", "risk": 3},
    {"a": "C", "b": "D", "risk": 4},
    {"a": "A", "b": "D", "risk": 6}
  ],
  "rounds": [
    {"closed": [1,2,3,4,5,6],
     "readings": {"P": true, "A": true, "B": true, "C": true, "D": true}},
    {"closed": [1,3,4,5],
     "readings": {"P": true, "A": true, "B": true, "C": false, "D": false}},
    {"closed": [2,4,6],
     "readings": {"P": true, "A": false, "B": true, "C": false, "D": false}}
  ]
}
```

可行时返回（节选）：

```json
{
  "feasible": true,
  "candidates_evaluated": 64,
  "explanation": {
    "failed_cables": [4],
    "failed_count": 1,
    "total_risk": 3.0,
    "cables": [{"index": 4, "a": "B", "b": "C", "risk": 3, "failed": true}],
    "rounds": [
      {"round_index": 1,
       "closed": [1,3,4,5],
       "reachable_sensors": ["P", "A", "B"],
       "matched": true,
       "readings": [
         {"node": "P", "expected": true, "actual": true, "match": true}
       ]}
    ]
  }
}
```

不可行时：

```json
{"feasible": false, "explanation": null,
 "message": "这些试验读数不能由同一组永久故障同时解释。",
 "candidates_evaluated": 64}
```

校验失败返回 `422`，响应体 `detail` 为中文原因（节点/电缆/轮次数量越界、
电源节点非法、读数缺失、风险为负等）。

## 测试

```bash
pytest -q                 # 引擎 + API 共 26 个测试
python scripts/verify.py  # 与容器 verify 服务同构的本地一键验收
```

## 设计说明

* **为什么单轮会漏判**：示例环网第 1 轮所有电缆闭合，即便 #4(B–C) 已断，环网
  替代通路仍让所有传感器通电；只有联合第 2、3 轮的部分闭合读数，才能锁定 #4。
* **完备性**：枚举所有故障组合（不做剪枝），保证不遗漏多故障的共同解释；
  m ≤ 14 规模下 2^14 组合 × 最多 7 轮 DFS 在毫秒级完成。
* **无状态结论**：服务端不保存归因结论；"修改草稿后不得保留旧结论"由前端
  在任何草稿变更时清空结果区并提示重新归因，服务端每次请求独立重算。
