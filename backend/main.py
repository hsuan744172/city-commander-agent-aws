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
  GET  /api/cameras        → 全路段即時影像攝影機對照表
  GET  /api/cameras/{id}   → 單一路段鄰近即時影像攝影機
  GET  /api/cameras/{id}/{cam}/stream   → MJPEG 代理串流
  GET  /api/cameras/{id}/{cam}/snapshot → 單張畫面
  GET  /api/cameras/{id}/{cam}/frame    → 畫面年齡與上游狀態
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

from fastapi import FastAPI, Query, Response, WebSocket, WebSocketDisconnect, UploadFile  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse, StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, ValidationError  # noqa: E402

from backend import camera_stream, sim_clock  # noqa: E402
from backend.agents.architect import run_commander  # noqa: E402
from backend.data_source import data_source_status, get_data_path  # noqa: E402

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAX_UPLOAD_INCIDENTS = int(os.environ.get("MAX_UPLOAD_INCIDENTS", "3"))
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", "1048576"))

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
        await camera_stream.shutdown()
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

        # --- 人流密度觀測站 (signaling_crowd_density.csv) — 帶插值 ---
        stations = []
        crowd_csv = get_data_path("signaling_crowd_density.csv")
        if crowd_csv.exists():
            try:
                crowd_df = pd.read_csv(crowd_csv, parse_dates=["Timestamp"])
                # 解析 Roaming_User_Pct 欄位（去掉 % 符號）
                crowd_df["_roaming_num"] = (
                    crowd_df["Roaming_User_Pct"]
                    .astype(str).str.replace("%", "", regex=False)
                    .astype(float)
                )

                for bs_id, group in crowd_df.groupby("BS_ID"):
                    group = group.sort_values("Timestamp")
                    past = group[group["Timestamp"] <= current]
                    future = group[group["Timestamp"] > current]

                    if past.empty:
                        # 時鐘早於資料集起點，用第一筆
                        row = group.iloc[0]
                        weight = 0.0
                    elif future.empty:
                        # 時鐘已超過資料集末尾，用最後一筆
                        row = past.iloc[-1]
                        weight = 0.0
                    else:
                        # 在兩筆之間做線性插值
                        prev_row = past.iloc[-1]
                        next_row = future.iloc[0]
                        t0 = prev_row["Timestamp"]
                        t1 = next_row["Timestamp"]
                        span = (t1 - t0).total_seconds()
                        elapsed = (current - t0).total_seconds()
                        weight = elapsed / span if span > 0 else 0.0

                        # 插值數值欄位
                        user_count = int(prev_row["User_Count"] + weight * (next_row["User_Count"] - prev_row["User_Count"]))
                        stay_time = int(prev_row["Stay_Time_Avg"] + weight * (next_row["Stay_Time_Avg"] - prev_row["Stay_Time_Avg"]))
                        growth_rate = round(prev_row["Growth_Rate"] + weight * (next_row["Growth_Rate"] - prev_row["Growth_Rate"]), 3)
                        roaming_pct = round(prev_row["_roaming_num"] + weight * (next_row["_roaming_num"] - prev_row["_roaming_num"]), 1)

                        stations.append({
                            "bs_id": bs_id,
                            "location_name": prev_row["Location_Name"],
                            "user_count": user_count,
                            "stay_time_avg": stay_time,
                            "growth_rate": growth_rate,
                            "roaming_user_pct": roaming_pct,
                            "data_as_of": current.strftime(sim_clock.TIME_FMT),
                        })
                        continue

                    # 非插值情況（首筆或末筆）
                    stations.append({
                        "bs_id": bs_id,
                        "location_name": row["Location_Name"],
                        "user_count": int(row["User_Count"]),
                        "stay_time_avg": int(row["Stay_Time_Avg"]),
                        "growth_rate": round(float(row["Growth_Rate"]), 2),
                        "roaming_user_pct": float(row["_roaming_num"]),
                        "data_as_of": pd.Timestamp(row["Timestamp"]).strftime(sim_clock.TIME_FMT),
                    })

                stations.sort(key=lambda s: s["bs_id"])
            except Exception as e:
                logger.warning(f"人流密度資料讀取失敗: {type(e).__name__}: {e}")

        return {
            "timestamp": ts_str,          # 當下模擬時間 (前端主要顯示這個)
            "sim_time": ts_str,
            "data_as_of": data_as_of,     # 資料實際最新量測時間
            "is_time_override": forced is not None,
            "clock": sim_clock.state(),
            "total_segments": len(segments),
            "segments": segments,
            "stations": stations,
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
        "data_source": data_source_status(),
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
    json_path = get_data_path("road_network_geometry.json")
    if not json_path.exists():
        return JSONResponse(content={"segments": []})

    with open(json_path, encoding="utf-8") as f:
        segments = json.load(f)

    return {"total_segments": len(segments), "segments": segments}


# --- 路段即時影像 -----------------------------------------------------------

# 對照表由 scripts/build_camera_map.py 離線產生（來源：twipcam 公開 CCTV 清單）。
# 靜態資料，程序啟動後只讀一次；純粹供畫面呈現，不參與 SOP 判定與 ETE 計算。
_CAMERA_MAP: dict | None = None


def _load_camera_map() -> dict:
    global _CAMERA_MAP
    if _CAMERA_MAP is None:
        json_path = DATA_DIR / "segment_cameras.json"
        if not json_path.exists():
            logger.warning("找不到 segment_cameras.json，即時影像功能停用")
            _CAMERA_MAP = {"segments": {}}
        else:
            with open(json_path, encoding="utf-8") as f:
                _CAMERA_MAP = json.load(f)
    return _CAMERA_MAP


def _camera_source(data: dict) -> dict:
    return {
        "source": data.get("source", ""),
        "source_page": data.get("source_page", ""),
        # 直播影像的實際提供者（快照與直播來源不同）
        "stream_source": data.get("stream_source", ""),
        "generated_at": data.get("generated_at", ""),
    }


@app.get("/api/cameras")
async def all_cameras():
    """全路段 → 鄰近即時影像攝影機對照表。靜態資料，不隨模擬時鐘變動。"""
    data = _load_camera_map()
    segments = data.get("segments", {})
    return {
        **_camera_source(data),
        "max_distance_m": data.get("max_distance_m"),
        "total_segments": len(segments),
        "segments": segments,
    }


@app.get("/api/cameras/{segment_id}")
async def segment_cameras(segment_id: str):
    """
    單一路段的鄰近即時影像攝影機清單，依「路名命中 → 距離」排序。
    前端以 snapshot_url 定時重抓快照模擬串流。
    """
    data = _load_camera_map()
    entry = (data.get("segments") or {}).get(segment_id)

    if entry is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": f"路段 {segment_id} 無攝影機對照資料",
                "segment_id": segment_id,
                "cameras": [],
            },
        )

    return {
        "segment_id": segment_id,
        "road_name": entry.get("road_name", ""),
        **_camera_source(data),
        "total": len(entry.get("cameras", [])),
        "cameras": entry.get("cameras", []),
    }


def _find_camera(segment_id: str, camera_id: str) -> dict | None:
    """
    從對照表查出指定鏡頭。只有白名單內的鏡頭能被代理，
    上游網址不接受呼叫端指定，避免代理端點變成 SSRF 跳板。
    """
    entry = (_load_camera_map().get("segments") or {}).get(segment_id)
    if not entry:
        return None
    for cam in entry.get("cameras", []):
        if cam.get("camera_id") == camera_id:
            return cam
    return None


def _camera_ref(segment_id: str, cam: dict) -> camera_stream.CameraRef:
    return camera_stream.CameraRef(
        segment_id=segment_id,
        camera_id=cam["camera_id"],
        url=cam["snapshot_url"],
        name=cam.get("name", ""),
    )


@app.get("/api/cameras/{segment_id}/{camera_id}/stream")
async def camera_mjpeg_stream(segment_id: str, camera_id: str):
    """
    以 multipart/x-mixed-replace 代理該鏡頭畫面，前端一個 <img> 即可持續顯示。

    上游只有定時更新的 JPEG 快照，這裡把輪詢轉封裝成串流：同一支鏡頭不論幾個
    前端在看都只向上游抓一次，前端也不必直連第三方網域。
    """
    cam = _find_camera(segment_id, camera_id)
    if cam is None:
        return JSONResponse(
            status_code=404,
            content={"error": f"路段 {segment_id} 無鏡頭 {camera_id}"},
        )

    ref = _camera_ref(segment_id, cam)

    # 先確認取得到畫面，才回 200 串流；否則回 502 讓前端顯示無訊號
    try:
        await camera_stream.prime(ref)
    except camera_stream.UpstreamError as e:
        logger.warning(f"街景來源不可用 {ref.key}: {e}")
        return JSONResponse(
            status_code=502,
            content={"error": "影像目前無法取得", "camera_id": camera_id, "detail": str(e)},
        )

    return StreamingResponse(
        camera_stream.stream(ref),
        media_type=camera_stream.MJPEG_CONTENT_TYPE,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
            # 反向代理若做緩衝會讓串流卡住
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/cameras/{segment_id}/{camera_id}/snapshot")
async def camera_snapshot(segment_id: str, camera_id: str):
    """單張畫面。前端暫停時顯示這個，也作為不支援 MJPEG 時的退路。"""
    cam = _find_camera(segment_id, camera_id)
    if cam is None:
        return JSONResponse(
            status_code=404,
            content={"error": f"路段 {segment_id} 無鏡頭 {camera_id}"},
        )

    try:
        frame = await camera_stream.prime(_camera_ref(segment_id, cam))
    except camera_stream.UpstreamError as e:
        return JSONResponse(
            status_code=502,
            content={"error": "影像目前無法取得", "detail": str(e)},
        )

    return Response(
        content=frame.data,
        media_type=frame.content_type,
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/cameras/{segment_id}/{camera_id}/frame")
async def camera_frame_info(segment_id: str, camera_id: str):
    """
    畫面實際狀態：上游宣告的拍攝時間與距今秒數。

    <img> 讀不到上游的 Last-Modified，只有後端拿得到。前端據此顯示畫面年齡，
    而不是不分新舊一律標成 LIVE — 實測部分公開鏡頭的快照已數小時未更新。
    """
    cam = _find_camera(segment_id, camera_id)
    if cam is None:
        return JSONResponse(
            status_code=404,
            content={"error": f"路段 {segment_id} 無鏡頭 {camera_id}"},
        )

    info = await camera_stream.frame_info(_camera_ref(segment_id, cam))
    return {
        "segment_id": segment_id,
        "camera_id": camera_id,
        "name": cam.get("name", ""),
        "distance_m": cam.get("distance_m"),
        **info,
    }


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
    """上傳並驗證 live_incidents.json，再執行有限批次的應變分析。"""
    try:
        content = await file.read()
        if not content:
            return JSONResponse(status_code=400, content={"error": "上傳檔案不可為空"})
        if len(content) > MAX_UPLOAD_BYTES:
            return JSONResponse(
                status_code=400,
                content={"error": f"檔案超過大小限制（{MAX_UPLOAD_BYTES} bytes）"},
            )

        try:
            data = json.loads(content.decode("utf-8"))
        except UnicodeDecodeError:
            return JSONResponse(status_code=400, content={"error": "檔案必須是 UTF-8 編碼的 JSON"})
        except json.JSONDecodeError as exc:
            return JSONResponse(
                status_code=400,
                content={"error": f"JSON 解析失敗：第 {exc.lineno} 行第 {exc.colno} 欄格式錯誤"},
            )

        # 支援兩種格式：直接陣列 [...] 或 {"incidents": [...]}。
        if isinstance(data, list):
            raw_incidents = data
        elif isinstance(data, dict) and "incidents" in data:
            raw_incidents = data["incidents"]
        else:
            return JSONResponse(
                status_code=400,
                content={"error": "JSON 格式不正確，需為事件陣列或含 incidents 陣列的物件"},
            )

        if not isinstance(raw_incidents, list) or not raw_incidents:
            return JSONResponse(status_code=400, content={"error": "incidents 必須是至少包含一筆事件的陣列"})
        if len(raw_incidents) > MAX_UPLOAD_INCIDENTS:
            return JSONResponse(
                status_code=400,
                content={"error": f"單次最多可上傳 {MAX_UPLOAD_INCIDENTS} 件事件，請拆分檔案後重試"},
            )

        incidents = []
        for index, item in enumerate(raw_incidents, start=1):
            try:
                incidents.append(Incident.model_validate(item).model_dump())
            except ValidationError as exc:
                logger.info("上傳事件驗證失敗：第 %s 筆", index)
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": f"第 {index} 筆事件格式不正確，需至少提供 event_id",
                        "details": exc.errors(include_url=False),
                    },
                )

        session_id = f"upload_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        logger.info("開始處理上傳事件：檔案=%s，事件數=%s", file.filename, len(incidents))
        report = await asyncio.to_thread(
            run_commander, {"incidents": incidents}, session_id, ts,
        )
        logger.info(
            "上傳事件處理完成：session=%s，processed=%s，failed=%s",
            session_id,
            report.get("processed", 0),
            report.get("failed", 0),
        )
        return JSONResponse(content=report)
    except Exception:
        logger.exception("上傳事件處理失敗：檔案=%s", file.filename)
        return JSONResponse(status_code=500, content={"error": "事件處理失敗，請稍後重試"})


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
# Production dashboard hosting
# ---------------------------------------------------------------------------

# The App Runner image copies the Vite build here. Mounting this after API and
# WebSocket routes preserves same-origin /api and /ws access for the dashboard.
FRONTEND_DIST_DIR = PROJECT_ROOT / "frontend_dist"
if FRONTEND_DIST_DIR.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST_DIR, html=True), name="frontend")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("backend.main:app", host="0.0.0.0", port=port, reload=True)
