"""
City Commander Agent — FastAPI 後端入口

架構：FastAPI + Strands Agents SDK (Claude 3.5 via Bedrock)
部署：Docker → AWS App Runner

Endpoints:
  POST /api/incidents      → 注入事件，觸發完整應變流程
  POST /api/what-if        → What-if 情境問答
  GET  /api/status         → 路網即時狀態
  GET  /api/health         → Health check
  WS   /ws/dashboard       → 即時推播 (未來擴充)
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.agents.architect import run_commander

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# 載入 .env 檔案
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("City Commander Agent 啟動")
    yield
    logger.info("City Commander Agent 關閉")


app = FastAPI(
    title="City Commander Agent",
    description="城市應變指揮官 AI 交通決策系統",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request Models
# ---------------------------------------------------------------------------


class Incident(BaseModel):
    event_id: str
    type: str = ""
    location: str = ""
    affected_segment: str = ""
    status: str = ""
    severity: str = ""
    description: str = ""
    timestamp: str = ""


class IncidentsRequest(BaseModel):
    incidents: list[Incident]
    session_id: str = ""


class WhatIfRequest(BaseModel):
    prompt: str
    session_id: str = ""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "service": "city-commander-agent",
        "version": "2.0.0",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


@app.get("/api/status")
async def traffic_status():
    """回傳路網即時狀態 — 取有最多路段資料的最新時間點。"""
    import pandas as pd

    csv_path = DATA_DIR / "city_traffic_flow.csv"
    if not csv_path.exists():
        return JSONResponse(content={"error": "Traffic data not found"})

    df = pd.read_csv(csv_path, parse_dates=["Timestamp"])
    def _pct(v):
        s = str(v).replace("%", "").strip()
        f = float(s)
        return f / 100 if f > 1 else f
    df["Saturation_Score"] = df["Saturation_Score"].apply(_pct)

    # 找出涵蓋最多路段的最新時間點 (避免選到只有 1 筆的時間)
    ts_counts = df.groupby("Timestamp").size()
    best_ts = ts_counts[ts_counts == ts_counts.max()].index.max()
    latest = df[df["Timestamp"] == best_ts]

    segments = []
    for _, row in latest.iterrows():
        score = float(row["Saturation_Score"])
        level = "A" if score >= 0.95 else ("B" if score >= 0.85 else "Normal")
        segments.append({
            "segment_id": row["Segment_ID"],
            "road_name": row["Road_Name"],
            "saturation_score": score,
            "avg_speed": float(row["Avg_Speed"]),
            "vehicle_count": int(row["Vehicle_Count"]),
            "lane_status": row["Lane_Status"],
            "level": level,
        })

    return {"timestamp": best_ts.strftime("%Y-%m-%d %H:%M"), "total_segments": len(segments), "segments": segments}


@app.get("/api/trend")
async def traffic_trend():
    """回傳所有路段的時序飽和度資料供折線圖使用。"""
    import pandas as pd

    csv_path = DATA_DIR / "city_traffic_flow.csv"
    if not csv_path.exists():
        return JSONResponse(content={"data": []})

    df = pd.read_csv(csv_path, parse_dates=["Timestamp"])
    def _pct(v):
        s = str(v).replace("%", "").strip()
        f = float(s)
        return f / 100 if f > 1 else f
    df["Saturation_Score"] = df["Saturation_Score"].apply(_pct)

    # 所有路段 pivot
    all_segments = df["Segment_ID"].unique().tolist()
    pivot = df.pivot_table(
        index="Timestamp", columns="Segment_ID", values="Saturation_Score", aggfunc="first"
    ).reset_index().sort_values("Timestamp")

    data = []
    for _, row in pivot.iterrows():
        point = {"time": row["Timestamp"].strftime("%H:%M")}
        for seg in all_segments:
            point[seg] = round(row.get(seg, 0), 3) if pd.notna(row.get(seg)) else None
        data.append(point)

    return {"data": data}


@app.post("/api/incidents")
async def handle_incidents(request: IncidentsRequest):
    """注入事件，執行完整應變流程。"""
    incidents_data = [inc.model_dump() for inc in request.incidents]
    session_id = request.session_id or f"session_{datetime.now().strftime('%Y%m%d%H%M%S')}"

    report = run_commander(
        event={"incidents": incidents_data},
        session_id=session_id,
    )

    return JSONResponse(content=report)


@app.post("/api/incidents/upload")
async def upload_incidents(file: UploadFile):
    """上傳 live_incidents.json 檔案，解析後注入系統。"""
    import json as json_mod

    try:
        content = await file.read()
        data = json_mod.loads(content.decode("utf-8"))

        # 支援兩種格式：直接陣列 [...] 或 {"incidents": [...]}
        if isinstance(data, list):
            incidents = data
        elif isinstance(data, dict) and "incidents" in data:
            incidents = data["incidents"]
        else:
            return JSONResponse(status_code=400, content={"error": "JSON 格式不正確，需為陣列或含 incidents 欄位"})

        session_id = f"upload_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        report = run_commander(event={"incidents": incidents}, session_id=session_id)
        return JSONResponse(content=report)

    except Exception as e:
        return JSONResponse(status_code=400, content={"error": f"檔案解析失敗: {type(e).__name__}: {e}"})


@app.post("/api/what-if")
async def handle_what_if(request: WhatIfRequest):
    """What-if 情境問答 (使用 Strands Agent)。"""
    from backend.agents.architect import run_what_if

    session_id = request.session_id or f"session_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    result = run_what_if(prompt=request.prompt, session_id=session_id)
    return JSONResponse(content=result)


# ---------------------------------------------------------------------------
# WebSocket (即時推播，未來擴充)
# ---------------------------------------------------------------------------

connected_clients: list[WebSocket] = []


@app.websocket("/ws/dashboard")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # 可接收前端指令
            payload = json.loads(data)
            if "incidents" in payload:
                incidents_data = payload["incidents"]
                report = run_commander(event={"incidents": incidents_data}, session_id="ws")
                await websocket.send_text(json.dumps(report, ensure_ascii=False))
    except WebSocketDisconnect:
        connected_clients.remove(websocket)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("backend.main:app", host="0.0.0.0", port=port, reload=True)
