"""
City Commander Agent — FastAPI 後端入口

架構：FastAPI + Strands Agents SDK (Amazon Bedrock Claude Sonnet)
部署：單一 Docker 映像 → Amazon ECR → Amazon ECS Fargate → Application Load Balancer

時間模型：
  後端內建離散模擬時鐘 (backend/sim_clock.py)，依真實時間逐格推進資料集。
  時鐘只會落在車流與人流「同時」具有完整切片的共同時間軸上，不做插值。
  前端只需要拉 GET /api/status 取「當下狀態」，不需要知道時間軸。
  任何端點都可用 ?ts=YYYY-MM-DD HH:MM 做單次時間覆寫（不影響全域時鐘，
  且覆寫時間可落在共同時間軸之外，此時才會啟用 traffic_math 的插值語意）。

Endpoints:
  GET  /api/status         → 路網當下狀態、SOP 第 1 條自動應變、資料型 SOP 主動偵測
  GET  /api/alert-summary  → 自動彈窗用的 LLM 預警摘要 (門檻判定仍由程式運算)
  GET  /api/sop            → SOP 條文原文與門檻表
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
  GET  /api/incidents/catalog → 可注入的路段/站點與 live_incidents.json 範本
  POST /api/incidents/preview → 嚴格驗證事件內容並回傳分類預覽 (不執行 Agent)
  POST /api/incidents/preview/upload → 上傳 live_incidents.json 取得預覽
  POST /api/incidents/inject  → 確認預覽後注入事件並推播給所有儀表板
  GET  /api/incidents/injections → 近期注入紀錄
  POST /api/what-if        → What-if 情境問答 (可呼叫 traffic_math 工具、保留對話記憶)
  POST /api/what-if/reset  → 清除指定 session 的對話記憶
  GET  /api/health         → Health check (?probe=true 會實際打一次 Bedrock)
  WS   /ws/dashboard       → 時間推進時主動推播當下狀態 / 注入後推播建議書
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv

# 載入 .env — 必須在 import backend 子模組之前，
# 因為模擬時鐘在載入時就會讀取 SIM_CLOCK_* 環境變數。
load_dotenv()

from fastapi import (  # noqa: E402
    FastAPI,
    Header,
    Query,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse, StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, ValidationError  # noqa: E402

from backend import camera_stream, sim_clock  # noqa: E402
from backend.agents import policy, sop_rules, traffic_math  # noqa: E402
from backend.agents.architect import run_commander  # noqa: E402
from backend.data_source import data_source_status, get_data_path  # noqa: E402
from backend.incident_response import (  # noqa: E402
    CONTRACT_VERSION,
    DEFAULT_HISTORY_LIMIT,
    TIMEZONE_LABEL,
    ApiError,
    ApiErrorDetail,
    ApiErrorResponse,
    EventInjectionService,
    IncidentPayloadValidationError,
    IncidentPreview,
    IncidentRecord,
    InjectionConfirmationError,
    PreviewMismatchError,
    parse_utc8_datetime,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
APP_VERSION = "3.0.0"
# 評審可能會加事件測試，原本的 3 件硬上限會直接擋掉。事件之間本來就併發處理，
# 提高上限只影響單次批次的耗時，不影響 60 秒預算下的單事件延遲。
MAX_UPLOAD_INCIDENTS = int(os.environ.get("MAX_UPLOAD_INCIDENTS", "10"))
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", "1048576"))

# 管理員注入介面的共用權杖。留空 = 不驗證（本機 Demo 預設）；
# 任何共用或公開部署都應設定，因為注入會觸發 Agent 執行並推播給所有儀表板。
INCIDENT_INJECT_TOKEN = (os.environ.get("INCIDENT_INJECT_TOKEN") or "").strip()

# 事件注入介面：目錄、預覽與注入紀錄都由這個服務提供，
# 驗證規則一律沿用 backend/incident_response 的嚴格契約層。
injection_service = EventInjectionService()

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
    version=APP_VERSION,
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
    # 人流事件（BS_）用這個欄位指出連帶受影響的車流路段，
    # live_incidents.json 的人群推擠事件就帶了 affected_road: RD_TPE_001。
    # 少了這個欄位，交通分級與 ETE 會找不到對應路段（命題所稱的人流↔車流融合）。
    affected_road: str = ""
    status: str = ""
    severity: str = ""
    description: str = ""
    timestamp: str = ""


class IncidentsRequest(BaseModel):
    incidents: list[Incident]
    session_id: str = ""
    # 本次分析要套用的模擬時間；留空 = 使用當下模擬時鐘
    sim_time: str = ""


class IncidentPreviewRequest(BaseModel):
    # live_incidents.json 的內容：事件陣列，或只含 incidents 陣列的物件。
    # 這裡刻意不做型別限制，驗證與分類一律交給嚴格契約層的 parser。
    payload: Any = None
    sim_time: str = ""


class IncidentInjectRequest(BaseModel):
    payload: Any = None
    # 預覽回傳的 preview_hash；帶上代表「注入的就是我剛看過的內容」。
    preview_hash: str = ""
    # 預覽要求的確認項目（payload、future_simulation）。
    confirmations: list[str] = []
    session_id: str = ""
    sim_time: str = ""


class WhatIfRequest(BaseModel):
    prompt: str
    session_id: str = ""
    sim_time: str = ""


class WhatIfSessionRequest(BaseModel):
    session_id: str


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


def _auto_advisory_for(segment: dict, ts_str: str) -> dict:
    """
    SOP 第 1 條對「城市應變觸發路段」的自動應變。

    B 級：通報交控中心啟動長綠燈時制，替代道路綠燈 +25%，並調度警力淨空路口。
    A 級：除上述外，同步觸發第 2 條替代路徑引導。

    ETE 的嚴重度：純壅塞沒有事故通報，SOP 第 7 條的 base_clearance 需要一個嚴重度，
    這裡依分級對應（A 級視同 Critical、B 級視同 High），並在輸出明確標示這是換算假設，
    不假裝它來自事件資料。
    """
    from backend.agents.traffic_math import (
        affected_segments_for_ete,
        build_signal_plan,
        calculate_ete,
        calculate_optimal_route,
    )

    seg_id = segment["segment_id"]
    level = segment["level"]
    severity = "Critical" if level == "A" else "High"

    advisory: dict = {
        "segment_id": seg_id,
        "road_name": segment["road_name"],
        "level": level,
        "level_description": sop_rules.level_description(level),
        "saturation_score": segment["saturation_score"],
        "is_trigger_segment": True,
        "triggered_by": (
            f"{segment['road_name']} 達 {sop_rules.level_description(level)}"
            f"（飽和度 {round(segment['saturation_score'] * 100)}%、"
            f"時速 {segment['avg_speed']} 公里）"
        ),
        "sop_reference": (
            "SOP 第 1 條：觸發路段達 A 級 → 長綠燈時制並同步觸發第 2 條替代路徑引導"
            if level == "A"
            else "SOP 第 1 條：觸發路段達 B 級 → 長綠燈時制並調度警力淨空路口"
        ),
    }

    route = None
    if level == "A":
        # A 級才做替代路徑引導；B 級依 SOP 只做號誌與警力
        route = calculate_optimal_route(seg_id, ts_str) or {}
        primary = route.get("primary_route")
        if isinstance(primary, dict):
            advisory["primary_route"] = primary.get("name", "")
            advisory["primary_route_id"] = primary.get("segment_id", "")
            advisory["primary_saturation"] = primary.get("saturation_score")
            advisory["selection_reason"] = route.get("selection_reason", "")
            advisory["selection_tier"] = route.get("selection_tier")
            advisory["secondary_routes"] = [
                {"name": c["name"], "saturation_score": c["saturation_score"]}
                for c in route.get("secondary_routes", [])
            ]
            advisory["excluded_routes"] = [
                {"name": c["name"], "reason": c["reason"]}
                for c in route.get("excluded_routes", [])
            ]
            advisory["upstream_resolution"] = route.get("upstream_resolution", {})
            # 完整候選評估表：每條替代道路的容量、相交、上下游與選用/排除理由，
            # 對應交付要求「說明排除其他候選之理由」
            advisory["route_candidates"] = route.get("all_candidates", [])

    # ETE：受影響路段的定義與事件建議書共用同一個函式，兩邊不會算出不同數字
    affected_ids = affected_segments_for_ete(seg_id, route)
    ete_data = calculate_ete(severity, affected_ids, ts_str)
    if ete_data and "ete_minutes" in ete_data:
        advisory["ete_minutes"] = ete_data["ete_minutes"]
        advisory["ete_breakdown"] = {
            "severity": ete_data["severity"],
            "severity_basis": (
                f"無事故通報，依 SOP 第 1 條分級換算嚴重度："
                f"{level} 級視同 {severity}"
            ),
            "base_clearance_minutes": ete_data["base_clearance_minutes"],
            "congestion_penalty_minutes": ete_data["congestion_penalty_minutes"],
            "avg_saturation_score": ete_data["avg_saturation_score"],
            "affected_segment_ids": ete_data["affected_segment_ids"],
            "formula": ete_data["formula"],
        }

    plan = build_signal_plan(
        seg_id,
        ts_str,
        advisory.get("ete_minutes"),
        advisory.get("primary_route_id", ""),
        scope=traffic_math.SIGNAL_SCOPE_SOP1,
    )
    if plan and "error" not in plan:
        advisory["signal_plan"] = plan
        advisory["signal_action"] = "、".join(
            f"{a['road_name']} {a['action']}" for a in plan.get("adjustments", [])
        )
        advisory["police_dispatch"] = plan.get("police_dispatch")
        advisory["window"] = plan.get("window", "")

    return advisory


def _build_status(ts: str | None = None) -> dict:
    """
    組裝路網當下狀態。

    ts 為空時使用模擬時鐘的當下時間。每個路段取「<= 當下時間」的最新一筆，
    因此資料集裡未來的時間點不會外洩給前端。

    自動應變只針對 SOP 第 1 條明列的城市應變觸發路段（忠孝東路四段、光復南路）；
    其餘路段達 A/B 級只做紅黃燈顯示，列在 monitored_alerts，不啟動長綠燈時制與
    替代路徑引導。這是原本會對全部 A 級路段發應變的過度觸發修正。
    """
    import pandas as pd

    from backend.agents.policy import evaluate_data_triggers
    from backend.agents.traffic_math import _get_time_slice, _load_traffic_flow, crowd_snapshot

    with sim_clock.override(ts) as forced:
        current = sim_clock.now()
        ts_str = current.strftime(sim_clock.TIME_FMT)

        latest, _ = _get_time_slice(_load_traffic_flow(), None, key_col="Segment_ID")

        segments = []
        for _, row in latest.iterrows():
            score = round(float(row["Saturation_Score"]), 4)
            level = sop_rules.assess_congestion_level(score)
            weight = float(row.get("Interp_Weight", 0.0) or 0.0)
            segments.append({
                "segment_id": row["Segment_ID"],
                "road_name": row["Road_Name"],
                "saturation_score": score,
                "avg_speed": round(float(row["Avg_Speed"]), 1),
                "vehicle_count": int(round(float(row["Vehicle_Count"]))),
                "lane_status": row["Lane_Status"],
                "level": level,
                "level_description": sop_rules.level_description(level),
                "is_trigger_segment": sop_rules.is_trigger_segment(row["Segment_ID"]),
                # 該路段這筆量測的實際時間 (可能早於當下時間)
                "data_as_of": pd.Timestamp(row["Timestamp"]).strftime(sim_clock.TIME_FMT),
                # 數值是否為插值結果，以及插到前後兩筆之間的哪個位置
                "is_interpolated": weight > 0,
                "interp_weight": round(weight, 3),
            })
        segments.sort(key=lambda s: s["segment_id"])

        abnormal = [s for s in segments if s["level"] in {"A", "B"}]

        # SOP 第 1 條：只有城市應變觸發路段會啟動應變
        auto_advisories = []
        for seg in [s for s in abnormal if s["is_trigger_segment"]]:
            try:
                auto_advisories.append(_auto_advisory_for(seg, ts_str))
            except Exception as e:
                logger.warning(
                    f"自動應變建議失敗 ({seg['segment_id']}): {type(e).__name__}: {e}"
                )
        # A 級優先呈現
        auto_advisories.sort(key=lambda a: (a["level"] != "A", -a["saturation_score"]))

        monitored_alerts = [
            {
                "segment_id": s["segment_id"],
                "road_name": s["road_name"],
                "level": s["level"],
                "level_description": s["level_description"],
                "saturation_score": s["saturation_score"],
                "avg_speed": s["avg_speed"],
                "note": "非 SOP 第 1 條城市應變觸發路段，僅供燈號顯示與監控",
            }
            for s in abnormal
            if not s["is_trigger_segment"]
        ]

        data_as_of = max((s["data_as_of"] for s in segments), default=None)

        # --- 人流密度觀測站 ---
        # 改走 traffic_math 的切片邏輯，與 SOP 第 3、4、6 條判定同源。
        # 原本這裡自己重寫一套線性插值且不看 SIM_DATA_MODE，導致生產環境
        # 路段是 as-of、站點卻是插值，畫面數字和後端判定會不一致。
        stations = []
        try:
            snapshot = crowd_snapshot(ts_str)
            for station in snapshot["stations"]:
                stations.append({
                    "bs_id": station["bs_id"],
                    "location_name": station["location_name"],
                    "user_count": station["user_count"],
                    "stay_time_avg": station["stay_time_avg"],
                    "growth_rate": station["growth_rate"],
                    # 統一為 0~1；顯示字串另給，避免前後端各用一套單位
                    "roaming_user_pct": station["roaming_user_pct"],
                    "roaming_user_pct_display": station["roaming_user_pct_display"],
                    "exceeds_sop6_threshold": station["exceeds_sop6_threshold"],
                    "data_as_of": station["data_as_of"],
                })
        except Exception as e:
            logger.warning(f"人流密度資料讀取失敗: {type(e).__name__}: {e}")

        # --- 資料型 SOP 主動偵測（第 3、4、6 條） ---
        try:
            triggers = evaluate_data_triggers(ts_str)
            data_triggers = {
                "query_timestamp": triggers["query_timestamp"],
                "data_as_of": triggers["data_as_of"],
                "triggered_numbers": triggers["triggered_numbers"],
                "multilingual_required": triggers["multilingual_required"],
                "languages": triggers["languages"],
                "checks": [
                    {
                        "sop_number": c["sop_number"],
                        "sop_title": c["sop_title"],
                        "triggered": c["triggered"],
                        "reason": c["reason"],
                        "evidence": c.get("evidence", {}),
                        "actions": c.get("actions", []),
                    }
                    for c in triggers["checks"]
                ],
                "roaming_trigger_stations": triggers["roaming_scan"]["trigger_stations"],
            }
        except Exception as e:
            logger.warning(f"資料型 SOP 判定失敗: {type(e).__name__}: {e}")
            data_triggers = {"triggered_numbers": [], "checks": []}

        return {
            "timestamp": ts_str,          # 當下模擬時間 (前端主要顯示這個)
            "sim_time": ts_str,
            "data_as_of": data_as_of,     # 資料實際最新量測時間
            "data_mode": os.environ.get("SIM_DATA_MODE", "interpolate"),
            "is_time_override": forced is not None,
            "clock": sim_clock.state(),
            "thresholds": sop_rules.thresholds_payload(),
            "total_segments": len(segments),
            "segments": segments,
            "stations": stations,
            "auto_advisories": auto_advisories,
            "monitored_alerts": monitored_alerts,
            "data_triggers": data_triggers,
            "has_alert": bool(abnormal or data_triggers.get("triggered_numbers")),
        }


async def _broadcast(message: dict) -> None:
    """把一則訊息推給所有 WebSocket 連線，順手清掉已斷線的 socket。"""
    if not connected_clients:
        return

    text = json.dumps(message, ensure_ascii=False, default=str)
    for ws in list(connected_clients):
        try:
            await ws.send_text(text)
        except Exception:
            with contextlib.suppress(ValueError):
                connected_clients.remove(ws)


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
            await _broadcast({"type": "status", **payload})
            last_sent = current
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"狀態推播失敗: {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/api/health")
async def health(
    probe: bool = Query(
        False,
        description="true 時實際呼叫一次 Bedrock 驗證模型可用（會產生少量費用與延遲）",
    ),
):
    """
    容器與 ALB 健康檢查。

    ALB 走預設路徑（不做 Bedrock 探測）以免每次健康檢查都呼叫模型。
    Demo 前請手動打一次 `?probe=true`：模型 ID 或 IAM 只要有一點不對，
    所有 LLM 功能會靜默退回確定性 fallback，畫面看起來正常但其實沒接上 AI。
    """
    from backend.agents.architect import bedrock_settings, probe_bedrock

    payload = {
        "status": "ok",
        "service": "city-commander-agent",
        "version": APP_VERSION,
        "timestamp": datetime.now().strftime(sim_clock.TIME_FMT),
        "sim_time": sim_clock.now_str(),
        "clock_mode": sim_clock.state()["mode"],
        "data_mode": os.environ.get("SIM_DATA_MODE", "interpolate"),
        "data_source": data_source_status(),
        "bedrock": bedrock_settings(),
    }
    if probe:
        payload["bedrock_probe"] = await asyncio.to_thread(probe_bedrock)
    return payload


@app.get("/api/sop")
async def sop_clauses(section: str | None = Query(None, description="條號或關鍵字，留空取全部")):
    """
    SOP 條文原文。前端用來在建議書與對話回覆旁顯示引用依據，
    讓判定結果可以直接對照條文本身。
    """
    if section:
        return policy.read_traffic_sop(section)
    data = policy.read_traffic_sop()
    clauses = policy.parse_clauses(data.get("sop_text", ""))
    return {
        "source": data.get("source", "local"),
        "total": len(clauses),
        "thresholds": sop_rules.thresholds_payload(),
        "clauses": [clauses[number] for number in sorted(clauses)],
    }


@app.get("/api/alert-summary")
async def alert_summary(
    ts: str | None = Query(None, description="單次時間覆寫，格式 YYYY-MM-DD HH:MM"),
):
    """
    儀表板自動彈窗用的預警摘要。

    命題要求「門檻判定由程式運算、摘要由 LLM 生成」：門檻與 SOP 觸發在
    _build_status / policy 算完後才交給 LLM 寫成摘要，LLM 不參與判定。
    結果依「時間 + 異常特徵」快取，時間沒推進不會重複呼叫 Bedrock。
    """
    from backend.agents.architect import generate_alert_summary

    def build() -> dict:
        status = _build_status(ts)
        return generate_alert_summary(
            status, status.get("data_triggers"), status.get("sim_time")
        )

    return await asyncio.to_thread(build)


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
    調整時鐘。時鐘為離散式，只會落在車流與人流都有完整切片的共同時間軸上。範例：
      {"mode": "playback", "interval": 1}       每 1 秒跳一格共同時間切片 (預設模式)
      {"mode": "playback", "interval": 5}       每 5 秒跳一格，適合較慢的 Demo 節奏
      {"sim_time": "2026-05-20 21:30"}          跳到指定時間 (沿用目前模式，會對齊共同時間軸)
      {"mode": "fixed", "sim_time": "2026-05-20 22:15"}  凍結在該時間
      {"mode": "latest"}                        永遠停在共同時間軸最後一格
    注意：smooth 與 auto 為相容用的舊模式別名，節奏與 playback 相同。
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
        json_path = get_data_path("segment_cameras.json")
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


# --- 管理員事件注入介面 -----------------------------------------------------
#
# 注入是三段式：目錄 → 預覽 → 確認注入。
# 驗證與分類全部委派給 backend/incident_response 的嚴格契約層，
# 所以注入介面與上傳介面不可能各自長出一套規則。


def _admin_denied(token: str | None) -> JSONResponse | None:
    """管理員端點的選用共用權杖檢查。

    未設定 INCIDENT_INJECT_TOKEN 時完全開放，保留本機 Demo 的便利性。
    共用或公開部署務必設定：注入會啟動 Agent 執行並推播給所有連線的儀表板。
    """
    if not INCIDENT_INJECT_TOKEN:
        return None
    if token and secrets.compare_digest(token, INCIDENT_INJECT_TOKEN):
        return None
    return _api_error_response(
        code="INCIDENT_ADMIN_FORBIDDEN",
        message="事件注入需要管理員權杖",
        path="X-Admin-Token",
        detail_code="admin_token_invalid",
        detail_message="請於 X-Admin-Token 標頭提供正確權杖",
        status_code=403,
    )


def _api_error_response(
    *,
    code: str,
    message: str,
    path: str,
    detail_code: str,
    detail_message: str,
    status_code: int,
) -> JSONResponse:
    """組出契約層的錯誤信封，內容只含穩定代碼與可安全外流的訊息。"""
    trace_id = uuid4().hex
    logger.info("事件注入請求被拒：code=%s trace=%s", code, trace_id)
    envelope = ApiErrorResponse(
        error=ApiError(
            code=code,
            message=message,
            trace_id=trace_id,
            details=(
                ApiErrorDetail(path=path, code=detail_code, message=detail_message),
            ),
        )
    )
    return JSONResponse(status_code=status_code, content=envelope.model_dump(mode="json"))


def _incident_error_response(exc, *, status_code: int, context: str) -> JSONResponse:
    """把契約層的驗證/確認錯誤轉成同一種錯誤信封。"""
    trace_id = uuid4().hex
    logger.info(
        "事件注入被拒（%s）：code=%s trace=%s", context, getattr(exc, "code", "?"), trace_id
    )
    envelope = ApiErrorResponse(error=exc.as_api_error(trace_id=trace_id))
    return JSONResponse(status_code=status_code, content=envelope.model_dump(mode="json"))


def _resolve_injection_clock(sim_time: str) -> str:
    """決定這次注入要對齊的模擬時間，留空即使用當下模擬時鐘。"""
    requested = (sim_time or "").strip()
    if not requested:
        return sim_clock.now_str()
    parse_utc8_datetime(requested)  # 格式錯誤時丟 ValueError
    return requested


def _invalid_sim_time_response() -> JSONResponse:
    return _api_error_response(
        code="INCIDENT_SIM_TIME_INVALID",
        message="模擬時間格式無效",
        path="sim_time",
        detail_code="datetime",
        detail_message="請使用 UTC+8 的 YYYY-MM-DD HH:MM 格式",
        status_code=400,
    )


def _preview_response(preview: IncidentPreview) -> dict:
    return {
        "contract_version": CONTRACT_VERSION,
        "timezone": TIMEZONE_LABEL,
        "preview": preview.model_dump(mode="json"),
    }


def _agent_incident(record: IncidentRecord) -> dict:
    """把驗證後的事件投影成 Agent 讀得懂的 dict。

    category 與 original_index 是契約層自己推導出來的欄位，不往下傳，
    避免 Agent 端出現第二套分類來源。
    """
    data = record.model_dump(mode="json")
    for derived in ("category", "original_index"):
        data.pop(derived, None)
    return {key: value for key, value in data.items() if value is not None}


@app.get("/api/incidents/catalog")
async def incident_injection_catalog(
    refresh: bool = Query(False, description="強制重新讀取資料來源"),
):
    """
    事件注入目錄：可引用的路段與人流站點、合法列舉值，
    以及 data/live_incidents.json 內建的事件範本（含推導出的事件分類）。
    """
    catalog = await asyncio.to_thread(injection_service.catalog, refresh=refresh)
    return {
        "contract_version": CONTRACT_VERSION,
        "timezone": TIMEZONE_LABEL,
        "sim_time": sim_clock.now_str(),
        "requires_admin_token": bool(INCIDENT_INJECT_TOKEN),
        **catalog.as_api_dict(),
    }


@app.post("/api/incidents/preview")
async def preview_incidents(request: IncidentPreviewRequest):
    """
    嚴格驗證 live_incidents.json 內容並回傳預覽：事件分類、可能觸發的 SOP 條號、
    是否含有超過當下模擬時間的事件，以及注入前必須回覆的確認項目。此端點不執行 Agent。
    """
    try:
        clock_time = _resolve_injection_clock(request.sim_time)
    except (TypeError, ValueError):
        return _invalid_sim_time_response()

    try:
        preview = await asyncio.to_thread(
            injection_service.preview_json,
            request.payload,
            simulation_clock_time=clock_time,
        )
    except IncidentPayloadValidationError as exc:
        return _incident_error_response(exc, status_code=400, context="preview")

    return JSONResponse(content=_preview_response(preview))


@app.post("/api/incidents/preview/upload")
async def preview_uploaded_incidents(
    file: UploadFile,
    ts: str | None = Query(None, description="本次注入要對齊的模擬時間"),
):
    """上傳 live_incidents.json 取得同一份預覽；副檔名、大小與編碼規則由契約層把關。"""
    try:
        clock_time = _resolve_injection_clock(ts or "")
    except (TypeError, ValueError):
        return _invalid_sim_time_response()

    content = await file.read()
    try:
        preview = await asyncio.to_thread(
            injection_service.preview_upload,
            filename=file.filename or "",
            content=content,
            simulation_clock_time=clock_time,
        )
    except IncidentPayloadValidationError as exc:
        return _incident_error_response(exc, status_code=400, context="preview_upload")

    return JSONResponse(content=_preview_response(preview))


@app.post("/api/incidents/inject")
async def inject_incidents(
    request: IncidentInjectRequest,
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
):
    """
    管理員注入事件：重新驗證 → 比對預覽雜湊 → 檢查確認項目 → 執行完整應變流程，
    最後把建議書推播給所有連線的儀表板並留存注入紀錄。
    """
    denied = _admin_denied(x_admin_token)
    if denied is not None:
        return denied

    try:
        clock_time = _resolve_injection_clock(request.sim_time)
    except (TypeError, ValueError):
        return _invalid_sim_time_response()

    # 注入前重新走一次預覽：確認項目與雜湊都對照「現在」的驗證結果，
    # 不信任呼叫端自己算出來的預覽。
    try:
        preview = await asyncio.to_thread(
            injection_service.preview_json,
            request.payload,
            simulation_clock_time=clock_time,
        )
        injection_service.verify_preview_hash(preview, request.preview_hash)
        injection_service.verify_confirmations(preview, request.confirmations)
    except IncidentPayloadValidationError as exc:
        return _incident_error_response(exc, status_code=400, context="inject")
    except InjectionConfirmationError as exc:
        return _incident_error_response(exc, status_code=400, context="inject")
    except PreviewMismatchError as exc:
        return _incident_error_response(exc, status_code=409, context="inject")

    incidents = [
        _agent_incident(record) for record in preview.normalized_payload.incidents
    ]
    session_id = (
        request.session_id or f"inject_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    )
    logger.info(
        "開始注入事件：session=%s，preview=%s，事件數=%s，模擬時間=%s",
        session_id,
        preview.preview_id,
        len(incidents),
        clock_time,
    )

    try:
        report = await asyncio.to_thread(
            run_commander, {"incidents": incidents}, session_id, clock_time
        )
    except Exception:
        logger.exception("事件注入執行失敗：session=%s", session_id)
        envelope = ApiErrorResponse.internal(
            code="INCIDENT_RUN_FAILED", trace_id=uuid4().hex
        )
        return JSONResponse(status_code=500, content=envelope.model_dump(mode="json"))

    record = injection_service.record_injection(
        preview=preview, session_id=session_id, report=report
    )
    logger.info(
        "事件注入完成：session=%s，processed=%s，failed=%s",
        session_id,
        report.get("processed", 0),
        report.get("failed", 0),
    )

    # 其他值班席位的儀表板不必重新整理就會收到這份建議書。
    await _broadcast(
        {
            "type": "incident_report",
            "injection_id": record.injection_id,
            "event_ids": list(record.event_ids),
            "report": report,
        }
    )

    return JSONResponse(
        content={
            "contract_version": CONTRACT_VERSION,
            "timezone": TIMEZONE_LABEL,
            "injection": record.as_api_dict(include_report=False),
            "preview": preview.model_dump(mode="json"),
            "report": report,
        }
    )


@app.get("/api/incidents/injections")
async def list_incident_injections(
    limit: int = Query(5, ge=1, le=DEFAULT_HISTORY_LIMIT),
    include_report: bool = Query(False, description="是否一併回傳建議書內容"),
):
    """近期注入紀錄（新到舊）。重新整理後的儀表板可據此接回最後一份建議書。"""
    records = injection_service.recent_injections(limit=limit)
    return {
        "contract_version": CONTRACT_VERSION,
        "timezone": TIMEZONE_LABEL,
        "count": len(records),
        "injections": [
            record.as_api_dict(include_report=include_report) for record in records
        ],
    }


@app.post("/api/what-if")
async def handle_what_if(request: WhatIfRequest):
    """
    What-if 情境問答；LLM 只看得到當下模擬時間為止的路網與人流數據。

    顧問可呼叫 traffic_math / policy 工具取得確定性計算結果，因此回覆的替代路徑、
    ETE 與 SOP 觸發狀態與建議書同源。回應會附上實際引用到的條文原文與呼叫的工具。
    """
    from backend.agents.architect import run_what_if

    session_id = request.session_id or f"session_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    result = await asyncio.to_thread(
        run_what_if, request.prompt, session_id, request.sim_time or None,
    )
    return JSONResponse(content=result)


@app.post("/api/what-if/reset")
async def reset_what_if(request: WhatIfSessionRequest):
    """清除對話記憶。指揮官想從乾淨的情境重新問時使用。"""
    from backend.agents.architect import reset_chat_session

    reset_chat_session(request.session_id)
    return {"status": "reset", "session_id": request.session_id}


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
