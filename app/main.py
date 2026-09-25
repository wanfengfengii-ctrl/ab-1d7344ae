"""深海观测网电缆永久故障归因 —— Web/API 服务。"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .engine import ValidationError, build_network, diagnose, serialize_result

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="深海观测网故障归因", version="1.0.0")


class CableIn(BaseModel):
    a: str
    b: str
    risk: float = Field(default=1.0, ge=0)


class RoundIn(BaseModel):
    # 闭合电缆编号（1-based）；传感器读数：true 通电 / false 断电
    closed: list[int] = Field(default_factory=list)
    readings: dict[str, bool]


class DiagnoseIn(BaseModel):
    name: str = Field(default="未命名方案")
    nodes: list[str]
    source: str
    cables: list[CableIn]
    rounds: list[RoundIn]


@app.get("/api/health")
def api_health() -> dict:
    return {"status": "ok", "service": "api"}


@app.post("/api/diagnose")
def api_diagnose(payload: DiagnoseIn) -> JSONResponse:
    data = payload.model_dump()
    try:
        network = build_network(data)
        result = diagnose(data, complete=True)
    except ValidationError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    body = serialize_result(network, result)
    body["name"] = payload.name
    return JSONResponse(body)


@app.get("/health")
def web_health() -> dict:
    return {"status": "ok", "service": "web"}


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("APP_HOST", "0.0.0.0")
    port = int(os.environ.get("APP_PORT", "8000"))
    uvicorn.run("app.main:app", host=host, port=port)
