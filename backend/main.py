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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
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
    """回傳路網即時狀態摘要。"""
    import pandas as pd

    csv_path = DATA_DIR / "city_traffic_flow.csv"
    if not csv_path.exists():
        return JSONResponse(content={"error": "Traffic data not found"})

    df = pd.read_csv(csv_path, parse_dates=["Timestamp"])
    if df["Saturation_Score"].dtype == object:
        df["Saturation_Score"] = df["Saturation_Score"].str.rstrip("%").astype(float)
        df.loc[df["Saturation_Score"] > 1, "Saturation_Score"] /= 100

    latest_ts = df["Timestamp"].max()
    latest = df[df["Timestamp"] == latest_ts]

    segments = []
    for _, row in latest.iterrows():
        score = float(row["Saturation_Score"])
        if score >= 0.95:
            level = "A"
        elif score >= 0.85:
            level = "B"
        else:
            level = "Normal"

        segments.append({
            "segment_id": row["Segment_ID"],
            "road_name": row["Road_Name"],
            "saturation_score": score,
            "avg_speed": float(row["Avg_Speed"]),
            "vehicle_count": int(row["Vehicle_Count"]),
            "lane_status": row["Lane_Status"],
            "level": level,
        })

    return {
        "timestamp": latest_ts.strftime("%Y-%m-%d %H:%M"),
        "total_segments": len(segments),
        "segments": segments,
    }


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
