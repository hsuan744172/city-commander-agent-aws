"""
City Commander Agent — FastAPI 後端入口

架構：FastAPI + Strands Agents SDK (Claude 3.5 via Bedrock)
部署：Docker → AWS App Runner

時間模型：
  後端內建模擬時鐘 (backend/sim_clock.py)，自己依真實時間推進並輪播資料集。
  前端只需要拉 GET /api/status 取「當下狀態」，不需要知道時間軸。
  任何端點都可用 ?ts=YYYY-MM-DD HH:MM 做單次時間覆寫（不影響全域時鐘）。

Endpoints:
  GET  /api/status         → 路網當下狀態 (依模擬時鐘)
  GET  /api/trend          → 截至當下的飽和度時序
  GET  /api/network        → 路網靜態幾何
  GET  /api/timeline       → 資料集所有時間點
  GET  /api/clock          → 模擬時鐘狀態
  POST /api/clock          → 調整時鐘 (mode / sim_time / speed / interval / loop)
  POST /api/clock/advance  → 相對前進或後退
  POST /api/clock/pause    → 暫停 (凍結時間)
  POST /api/clock/resume   → 繼續
  POST /api/clock/reset    → 回到環境變數初始設定
  POST /api/incidents      → 注入事件，觸發完整應變流程
  POST /api/incidents/upload → 上傳事件 JSON
  POST /api/what-if        → What-if 情境問答
  GET  /api/health         → Health check
  WS   /ws/dashboard       → 時間推進時主動推播當下狀態
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# 載入 .env — 必須在 import backend 子模組之前，
# 因為模擬時鐘在載入時就會讀取 SIM_CLOCK_* 環境變數。
load_dotenv()

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect, UploadFile  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from backend import sim_clock  # noqa: E402
from backend.agents.architect import run_commander  # noqa: E402

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"

# 時間推進時是否主動推播到 WebSocket
PUSH_ON_TICK = (os.environ.get("SIM_CLOCK_PUSH", "true").strip().lower()
                in {"1", "true", "yes", "y", "on"})
PUSH_POLL_SECONDS = 1.0


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("City Commander Agent 啟動")
    logger.info(f"模擬時鐘: {sim_clock.state()}")
    pusher = asyncio.create_task(_broadcast_loop()) if PUSH_ON_TICK else None
    try:
        yield
    finally:
        if pusher:
            pusher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pusher
        logger.info("City Commander Agent 關閉")


app = FastAPI(
    title="City Commander Agent",
    description="城市應變指揮官 AI 交通決策系統",
    version="2.1.0",
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
    # 本次分析要套用的模擬時間；留空 = 使用當下模擬時鐘
    sim_time: str = ""


class WhatIfRequest(BaseModel):
    prompt: str
    session_id: str = ""
    sim_time: str = ""


class ClockSettings(BaseModel):
    mode: str | None = None          # smooth | playback | auto | fixed | latest
    sim_time: str | None = None      # 跳到指定時間
    speed: float | None = None       # auto 模式倍率
    interval: float | None = None    # smooth / playback 每個資料間隔耗費的秒數
    loop: bool | None = None         # 跑完是否從頭再播
    poll: float | None = None        # 連續模式下建議前端輪詢的秒數


class ClockAdvance(BaseModel):
    minutes: float | None = None     # 以模擬分鐘前進/後退
    steps: int | None = None         # 以資料集時間點前進/後退


# ---------------------------------------------------------------------------
# 狀態組裝 (HTTP 與 WebSocket 共用)
# ---------------------------------------------------------------------------


def _build_status(ts: str | None = None) -> dict:
    """
    組裝路網當下狀態。

    ts 為空時使用模擬時鐘的當下時間。每個路段取「<= 當下時間」的最新一筆，
    因此資料集裡未來的時間點不會外洩給前端。
    """
    import pandas as pd

    from backend.agents.traffic_math import (
        _get_time_slice,
        _load_traffic_flow,
        calculate_ete,
        calculate_optimal_route,
    )

    csv_path = DATA_DIR / "city_traffic_flow.csv"
    if not csv_path.exists():
        return {"error": "Traffic data not found", "segments": [], "auto_advisories": []}

    with sim_clock.override(ts) as forced:
        current = sim_clock.now()
        ts_str = current.strftime(sim_clock.TIME_FMT)

        latest, _ = _get_time_slice(_load_traffic_flow(), None, key_col="Segment_ID")

        segments = []
        for _, row in latest.iterrows():
            score = round(float(row["Saturation_Score"]), 4)
            level = "A" if score >= 0.95 else ("B" if score >= 0.85 else "Normal")
            weight = float(row.get("Interp_Weight", 0.0) or 0.0)
            segments.append({
                "segment_id": row["Segment_ID"],
                "road_name": row["Road_Name"],
                "saturation_score": score,
                "avg_speed": round(float(row["Avg_Speed"]), 1),
                "vehicle_count": int(round(float(row["Vehicle_Count"]))),
                "lane_status": row["Lane_Status"],
                "level": level,
                # 該路段這筆量測的實際時間 (可能早於當下時間)
                "data_as_of": pd.Timestamp(row["Timestamp"]).strftime(sim_clock.TIME_FMT),
                # 數值是否為插值結果，以及插到前後兩筆之間的哪個位置
                "is_interpolated": weight > 0,
                "interp_weight": round(weight, 3),
            })
        segments.sort(key=lambda s: s["segment_id"])

        # SOP 第 1 條 → A 級自動觸發第 2 條替代路徑
        auto_advisories = []
        for seg in [s for s in segments if s["level"] == "A"]:
            seg_id = seg["segment_id"]
            try:
                route = calculate_optimal_route(seg_id, ts_str)
                primary = (route or {}).get("primary_route")
                ete_data = calculate_ete("Critical", [seg_id], ts_str)

                advisory = {
                    "triggered_by": f"{seg['road_name']} 達 A 級癱瘓（飽和度 {round(seg['saturation_score'] * 100)}%）",
                    "sop_reference": "SOP 第 1 條 → 同步觸發第 2 條替代路徑引導",
                    "segment_id": seg_id,
                    "road_name": seg["road_name"],
                }

                if primary and isinstance(primary, dict):
                    advisory["primary_route"] = primary.get("name", "")
                    advisory["primary_saturation"] = primary.get("saturation_score", 0)
                    advisory["selection_reason"] = (route or {}).get("selection_reason", "")
                    advisory["signal_action"] = f"{primary.get('name', '')} 綠燈配時 +25%"

                if ete_data and "ete_minutes" in ete_data:
                    advisory["ete_minutes"] = ete_data["ete_minutes"]

                auto_advisories.append(advisory)
            except Exception as e:
                logger.warning(f"自動路徑建議失敗 ({seg_id}): {type(e).__name__}: {e}")

        data_as_of = max((s["data_as_of"] for s in segments), default=None)

        return {
            "timestamp": ts_str,          # 當下模擬時間 (前端主要顯示這個)
            "sim_time": ts_str,
            "data_as_of": data_as_of,     # 資料實際最新量測時間
            "is_time_override": forced is not None,
            "clock": sim_clock.state(),
            "total_segments": len(segments),
            "segments": segments,
            "auto_advisories": auto_advisories,
        }


async def _broadcast_loop() -> None:
    """模擬時間變動時，主動把當下狀態推播給所有 WebSocket 連線。"""
    last_sent: str | None = None
    while True:
        try:
            await asyncio.sleep(PUSH_POLL_SECONDS)
            if not connected_clients:
                last_sent = None
                continue

            current = sim_clock.now_str()
            if current == last_sent:
                continue

            payload = await asyncio.to_thread(_build_status)
            message = json.dumps({"type": "status", **payload}, ensure_ascii=False, default=str)

            for ws in list(connected_clients):
                try:
                    await ws.send_text(message)
                except Exception:
                    with contextlib.suppress(ValueError):
                        connected_clients.remove(ws)
            last_sent = current
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"狀態推播失敗: {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "service": "city-commander-agent",
        "version": "2.1.0",
        "timestamp": datetime.now().strftime(sim_clock.TIME_FMT),
        "sim_time": sim_clock.now_str(),
        "clock_mode": sim_clock.state()["mode"],
    }


# --- 模擬時鐘 ---------------------------------------------------------------


@app.get("/api/clock")
async def get_clock():
    """模擬時鐘狀態 + 資料集時間軸（前端做時間軸拉桿用）。"""
    return {
        **sim_clock.state(),
        "modes": list(sim_clock.MODES),
        "timeline": [t.strftime(sim_clock.TIME_FMT) for t in sim_clock.timeline()],
    }


@app.post("/api/clock")
async def set_clock(settings: ClockSettings):
    """
    調整時鐘。範例：
      {"mode": "smooth", "interval": 8}         每 8 秒走完一個資料間隔，數值連續插值 (預設模式)
      {"mode": "playback", "interval": 5}       每 5 秒「跳」一格，數值階梯狀
      {"mode": "auto", "speed": 120}            連續時間，120 倍速
      {"sim_time": "2026-05-20 21:30"}          跳到指定時間 (沿用目前模式)
      {"mode": "fixed", "sim_time": "2026-05-20 22:15"}  凍結在該時間
    """
    try:
        state = sim_clock.clock.configure(
            mode=settings.mode,
            sim_time=settings.sim_time,
            speed=settings.speed,
            interval=settings.interval,
            loop=settings.loop,
            poll=settings.poll,
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    logger.info(f"模擬時鐘已調整: {state}")
    return state


@app.post("/api/clock/advance")
async def advance_clock(payload: ClockAdvance):
    """相對移動時間。{"steps": 1} 下一格、{"steps": -1} 上一格、{"minutes": 30} 前進 30 分。"""
    try:
        return sim_clock.clock.advance(minutes=payload.minutes, steps=payload.steps)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


@app.post("/api/clock/pause")
async def pause_clock():
    return sim_clock.clock.pause()


@app.post("/api/clock/resume")
async def resume_clock():
    return sim_clock.clock.resume()


@app.post("/api/clock/reset")
async def reset_clock():
    return sim_clock.clock.reset()


@app.get("/api/timeline")
async def get_timeline():
    """資料集所有時間點，並標記目前播到哪一格。"""
    stamps = [t.strftime(sim_clock.TIME_FMT) for t in sim_clock.timeline()]
    state = sim_clock.state()
    return {
        "total": len(stamps),
        "timestamps": stamps,
        "current_index": state["timeline_index"],
        "current": state["sim_time"],
    }


# --- 資料 -------------------------------------------------------------------


@app.get("/api/status")
async def traffic_status_with_routing(
    ts: str | None = Query(None, description="單次時間覆寫，格式 YYYY-MM-DD HH:MM"),
):
    """
    回傳路網「當下」狀態（由後端模擬時鐘決定當下是幾點）。
    SOP 第 1 條：達 A 級時自動觸發第 2 條替代路徑引導。
    """
    return await asyncio.to_thread(_build_status, ts)


@app.get("/api/trend")
async def traffic_trend(
    ts: str | None = Query(None, description="單次時間覆寫"),
    full: bool = Query(False, description="true 則回傳完整時間軸（含未來資料）"),
    window_minutes: int | None = Query(None, description="只取當下往前 N 分鐘"),
    include_current: bool = Query(True, description="是否在尾端補上「當下」的插值點"),
):
    """
    回傳飽和度時序資料供折線圖使用；預設只到當下模擬時間，不洩漏未來。
    尾端會補一個「當下」的插值點，讓曲線隨時鐘連續延伸而非一格一格跳。
    """
    def build() -> dict:
        import pandas as pd

        from backend.agents.traffic_math import _get_time_slice, _load_traffic_flow

        csv_path = DATA_DIR / "city_traffic_flow.csv"
        if not csv_path.exists():
            return {"data": []}

        with sim_clock.override(ts):
            current = sim_clock.now()
            full_df = _load_traffic_flow()
            df = full_df

            if not full:
                df = df[df["Timestamp"] <= current]
                if window_minutes:
                    df = df[df["Timestamp"] >= current - pd.Timedelta(minutes=window_minutes)]

            if df.empty:
                return {
                    "data": [],
                    "sim_time": current.strftime(sim_clock.TIME_FMT),
                    "segments": [],
                    "truncated_to_sim_time": not full,
                }

            all_segments = sorted(df["Segment_ID"].unique().tolist())
            pivot = df.pivot_table(
                index="Timestamp", columns="Segment_ID", values="Saturation_Score", aggfunc="first"
            ).reset_index().sort_values("Timestamp")

            data = []
            for _, row in pivot.iterrows():
                point = {
                    "time": row["Timestamp"].strftime("%H:%M"),
                    "timestamp": row["Timestamp"].strftime(sim_clock.TIME_FMT),
                    "is_current": False,
                }
                for seg in all_segments:
                    value = row.get(seg)
                    point[seg] = round(value, 3) if pd.notna(value) else None
                data.append(point)

            # 尾端補上「當下」的插值點（用未截斷的資料才能插值）
            if not full and include_current:
                cur_slice, _ = _get_time_slice(full_df, None, key_col="Segment_ID")
                stamp = current.strftime(sim_clock.TIME_FMT)
                if not data or data[-1]["timestamp"] != stamp:
                    point = {
                        "time": current.strftime("%H:%M"),
                        "timestamp": stamp,
                        "is_current": True,
                    }
                    for seg in all_segments:
                        point[seg] = None
                    for _, r in cur_slice.iterrows():
                        seg = r["Segment_ID"]
                        if seg in point:
                            point[seg] = round(float(r["Saturation_Score"]), 3)
                    data.append(point)

            return {
                "data": data,
                "sim_time": current.strftime(sim_clock.TIME_FMT),
                "segments": all_segments,
                "truncated_to_sim_time": not full,
            }

    return await asyncio.to_thread(build)


@app.get("/api/network")
async def road_network():
    """
    回傳路網靜態幾何資訊（車道容量、路口、替代道路）。
    供 3D 街景視角依 capacity_vph 推算車道數與路寬。靜態資料，不隨時間變動。
    """
    json_path = DATA_DIR / "road_network_geometry.json"
    if not json_path.exists():
        return JSONResponse(content={"segments": []})

    with open(json_path, encoding="utf-8") as f:
        segments = json.load(f)

    return {"total_segments": len(segments), "segments": segments}


# --- 事件與問答 -------------------------------------------------------------


@app.post("/api/incidents")
async def handle_incidents(request: IncidentsRequest):
    """注入事件，執行完整應變流程。事件未帶 timestamp 時視為「當下」發生。"""
    incidents_data = [inc.model_dump() for inc in request.incidents]
    session_id = request.session_id or f"session_{datetime.now().strftime('%Y%m%d%H%M%S')}"

    report = await asyncio.to_thread(
        run_commander,
        {"incidents": incidents_data},
        session_id,
        request.sim_time or None,
    )

    return JSONResponse(content=report)


@app.post("/api/incidents/upload")
async def upload_incidents(
    file: UploadFile,
    ts: str | None = Query(None, description="本次分析套用的模擬時間"),
):
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
        report = await asyncio.to_thread(
            run_commander, {"incidents": incidents}, session_id, ts,
        )
        return JSONResponse(content=report)

    except Exception as e:
        return JSONResponse(status_code=400, content={"error": f"檔案解析失敗: {type(e).__name__}: {e}"})


@app.post("/api/what-if")
async def handle_what_if(request: WhatIfRequest):
    """What-if 情境問答；LLM 只看得到當下模擬時間為止的路網數據。"""
    from backend.agents.architect import run_what_if

    session_id = request.session_id or f"session_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    result = await asyncio.to_thread(
        run_what_if, request.prompt, session_id, request.sim_time or None,
    )
    return JSONResponse(content=result)


# ---------------------------------------------------------------------------
# WebSocket — 時間推進時主動推播當下狀態
# ---------------------------------------------------------------------------

connected_clients: list[WebSocket] = []


@app.websocket("/ws/dashboard")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    try:
        # 連上先給一份當下狀態，前端不必額外打一次 REST
        initial = await asyncio.to_thread(_build_status)
        await websocket.send_text(json.dumps({"type": "status", **initial}, ensure_ascii=False, default=str))

        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            if "incidents" in payload:
                report = await asyncio.to_thread(
                    run_commander,
                    {"incidents": payload["incidents"]},
                    "ws",
                    payload.get("sim_time"),
                )
                await websocket.send_text(json.dumps({"type": "report", **report}, ensure_ascii=False, default=str))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"WebSocket 異常: {type(e).__name__}: {e}")
    finally:
        with contextlib.suppress(ValueError):
            connected_clients.remove(websocket)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("backend.main:app", host="0.0.0.0", port=port, reload=True)
