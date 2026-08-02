"""
交通數學計算模組 — 嚴格依據 emergency_traffic_sop.txt 第 2、6、7 條。

⚠️ 全局約束：所有數值計算只在此模組執行，Agent 禁止自行推算。
   門檻與規則常數一律取自 backend/agents/sop_rules.py，此處不自行定義。
"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

import pandas as pd

from backend import sim_clock
from backend.agents import sop_rules
from backend.data_source import get_data_path

TRAFFIC_FLOW_FILE = "city_traffic_flow.csv"
ROAD_NETWORK_FILE = "road_network_geometry.json"
CROWD_DENSITY_FILE = "signaling_crowd_density.csv"

# 資料切片語意 (SIM_DATA_MODE)：
#   interpolate (預設) — 在前後兩筆量測之間對數值欄位做線性插值，數值連續變化。
#                        搭配 smooth/auto 時鐘模式可得平滑曲線。
#   asof              — 每個路段/基地台取「<= 查詢時間」的最新一筆 (forward fill)，
#                        數值呈階梯狀跳動。
#   exact             — 只取單一時間點的切片 (<= 查詢時間的最後一個時間點)。
#
# ⚠️ interpolate 會參考「下一筆」量測來做混合，因此嚴格來說會用到查詢時間之後的資料。
#    這對「重播一段已錄好的歷史」是合理的；若情境要求絕不觸碰未來資料，請用 asof。
DATA_MODE_ENV = "SIM_DATA_MODE"
DATA_MODES = ("interpolate", "asof", "exact")

# 這些欄位不參與插值 (時間欄與類別欄由「前一筆」延續)
NON_INTERPOLATED = {"Timestamp", "Interp_Weight"}


def _data_mode() -> str:
    mode = (os.environ.get(DATA_MODE_ENV) or "interpolate").strip().lower()
    return mode if mode in DATA_MODES else "interpolate"


def _safe_pct_to_float(series: pd.Series) -> pd.Series:
    """將可能含 % 的欄位統一轉為 0~1 浮點數。"""
    def convert(val):
        if isinstance(val, str):
            val = val.replace("%", "").strip()
            result = float(val)
            return result / 100 if result > 1 else result
        return float(val)
    return series.apply(convert)


# --- CSV 快取 (依 mtime 失效)：輪播時每秒可能被查詢多次，避免重複 IO ---------

_cache: dict[str, tuple[int, object]] = {}
_cache_lock = threading.Lock()


def _cached(path: Path, builder):
    stamp = path.stat().st_mtime_ns if path.exists() else 0
    key = str(path)
    with _cache_lock:
        hit = _cache.get(key)
        if hit and hit[0] == stamp:
            return hit[1]
    value = builder()
    with _cache_lock:
        _cache[key] = (stamp, value)
    return value


def _load_traffic_flow() -> pd.DataFrame:
    path = get_data_path(TRAFFIC_FLOW_FILE)

    def build() -> pd.DataFrame:
        df = pd.read_csv(path, parse_dates=["Timestamp"])
        df["Saturation_Score"] = _safe_pct_to_float(df["Saturation_Score"])
        return df.sort_values("Timestamp")
    return _cached(path, build).copy()


def _load_road_network() -> list[dict]:
    path = get_data_path(ROAD_NETWORK_FILE)

    def build() -> list[dict]:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return _cached(path, build)


def _load_crowd_density() -> pd.DataFrame:
    path = get_data_path(CROWD_DENSITY_FILE)

    def build() -> pd.DataFrame:
        df = pd.read_csv(path, parse_dates=["Timestamp"])
        df["Roaming_User_Pct"] = _safe_pct_to_float(df["Roaming_User_Pct"])
        return df.sort_values("Timestamp")
    return _cached(path, build).copy()


def _asof_rows(df: pd.DataFrame, ts: pd.Timestamp, key_col: str) -> pd.DataFrame:
    """每個 key 取 <= ts 的最新一筆。"""
    past = df[df["Timestamp"] <= ts]
    if past.empty:
        past = df[df["Timestamp"] == df["Timestamp"].min()]
    return past.loc[sorted(past.groupby(key_col)["Timestamp"].idxmax())]


def _interpolate_slice(df: pd.DataFrame, ts: pd.Timestamp, key_col: str) -> pd.DataFrame:
    """
    對每個 key，在「前一筆」與「後一筆」量測之間對數值欄位做線性插值。

    - Timestamp 保留前一筆的實際量測時間（data_as_of 的語意不變）
    - 類別欄位（Lane_Status 等）沿用前一筆，不做混合
    - 沒有後一筆（已到資料集尾端）→ 等同 as-of
    - 額外提供 Interp_Weight 欄位（0=剛好落在量測點，趨近 1=接近下一筆）
    """
    prev = _asof_rows(df, ts, key_col).set_index(key_col)

    future = df[df["Timestamp"] > ts]
    if future.empty:
        prev["Interp_Weight"] = 0.0
        return prev.reset_index()

    nxt = future.loc[sorted(future.groupby(key_col)["Timestamp"].idxmin())].set_index(key_col)
    aligned = nxt.reindex(prev.index)

    span = (aligned["Timestamp"] - prev["Timestamp"]).dt.total_seconds()
    weight = ((ts - prev["Timestamp"]).dt.total_seconds() / span).clip(0.0, 1.0)
    weight = weight.where(span > 0).fillna(0.0)

    out = prev.copy()
    for col in prev.columns:
        if col in NON_INTERPOLATED or not pd.api.types.is_numeric_dtype(prev[col]):
            continue
        delta = (aligned[col] - prev[col]).fillna(0.0)
        out[col] = prev[col] + delta * weight

    out["Interp_Weight"] = weight.round(4)
    return out.reset_index()


def _get_time_slice(
    df: pd.DataFrame,
    timestamp: str | None = None,
    key_col: str | None = None,
) -> tuple[pd.DataFrame, pd.Timestamp]:
    """
    取得查詢時間當下的資料切片。

    timestamp 為空時交由模擬時鐘決定當下時間 (backend/sim_clock.py)。
    回傳 (切片, 查詢時間)；查詢時間是模擬時鐘的當下時間，不一定是資料時間點。
    """
    ts = sim_clock.resolve(timestamp)
    if df is None or df.empty:
        return df, ts

    mode = _data_mode()

    if key_col and key_col in df.columns:
        if mode == "interpolate":
            return _interpolate_slice(df, ts, key_col), ts
        if mode == "asof":
            return _asof_rows(df, ts, key_col), ts

    past = df[df["Timestamp"] <= ts]
    if past.empty:
        # 查詢時間早於資料集起點 → 退回最早一筆，避免回傳空資料
        past = df[df["Timestamp"] == df["Timestamp"].min()]
    return past[past["Timestamp"] == past["Timestamp"].max()], ts


def data_as_of(time_df: pd.DataFrame) -> str | None:
    """切片中最新的資料時間點 (可能早於查詢時間)。"""
    if time_df is None or time_df.empty:
        return None
    return pd.Timestamp(time_df["Timestamp"].max()).strftime(sim_clock.TIME_FMT)


def get_current_traffic_context(timestamp: str | None = None) -> dict:
    """回傳可直接提供給 Agent 的完整路網資料，包含唯一依據時間。"""
    traffic_df = _load_traffic_flow()
    time_df, ts = _get_time_slice(traffic_df, timestamp, key_col="Segment_ID")
    data_timestamp = data_as_of(time_df) or ts.strftime(sim_clock.TIME_FMT)
    segments = []
    for _, row in time_df.iterrows():
        score = float(row["Saturation_Score"])
        level = sop_rules.assess_congestion_level(score)
        segments.append({
            "路段編號": row["Segment_ID"],
            "路段名稱": row["Road_Name"],
            "飽和度": f"{round(score * 100)}%",
            "SOP第1條分級": sop_rules.level_description(level),
            "城市應變觸發路段": sop_rules.is_trigger_segment(row["Segment_ID"]),
            "平均車速": f"{float(row['Avg_Speed']):g} 公里/小時",
            "車流量": f"{int(row['Vehicle_Count'])} 輛",
            "車道狀態": row["Lane_Status"],
        })
    return {
        "資料時間": data_timestamp,
        "路段總數": len(segments),
        "路段狀態": segments,
    }


# 趨勢方向的判定帶寬：飽和度變化在 ±1 個百分點內視為持平。
# 這不是 SOP 門檻（SOP 只規範分級門檻），純粹為了避免把量測雜訊講成「惡化中」。
TREND_FLAT_BAND = 0.01


def segment_saturation_trend(
    segment_id: str,
    timestamp: str | None = None,
    points: int = 6,
) -> dict:
    """
    單一路段的飽和度時序趨勢，供模組 1 的主動預警摘要與監控報告使用。

    只取「<= 查詢時間」的實際量測點，尾端再補上查詢時間當下的切片值，
    與 GET /api/status 顯示的飽和度同源，因此報告敘述與畫面數字不會對不上。

    回傳值全部是程式運算結果，LLM 只負責轉述，不得自行推算趨勢。
    """
    seg = str(segment_id or "").strip()
    ts = sim_clock.resolve(timestamp)
    now_stamp = ts.strftime(sim_clock.TIME_FMT)

    df = _load_traffic_flow()
    seg_df = df[df["Segment_ID"] == seg].sort_values("Timestamp")
    if seg_df.empty:
        return {
            "segment_id": seg,
            "road_name": "",
            "sim_time": now_stamp,
            "available": False,
            "points": [],
            "note": "查無該路段車流量測，不提供趨勢判讀",
        }

    past = seg_df[seg_df["Timestamp"] <= ts]
    if past.empty:
        past = seg_df.head(1)
    history = past.tail(max(1, int(points)))

    def describe(score: float, stamp: str, current: bool = False) -> dict:
        rounded = round(float(score), 4)
        return {
            "time": stamp,
            "saturation_score": rounded,
            "level": sop_rules.assess_congestion_level(rounded),
            "is_current": current,
        }

    series = [
        describe(row["Saturation_Score"], pd.Timestamp(row["Timestamp"]).strftime(sim_clock.TIME_FMT))
        for _, row in history.iterrows()
    ]

    # 尾端對齊「查詢時間當下」的切片（含 SIM_DATA_MODE 的插值語意）
    current_slice, _ = _get_time_slice(df, timestamp, key_col="Segment_ID")
    current_row = current_slice[current_slice["Segment_ID"] == seg]
    if not current_row.empty:
        current = describe(current_row.iloc[0]["Saturation_Score"], now_stamp, current=True)
        if series and series[-1]["time"] == now_stamp:
            series[-1] = current
        else:
            series.append(current)

    first_score = series[0]["saturation_score"]
    current_score = series[-1]["saturation_score"]
    delta = round(current_score - first_score, 4)

    if delta >= TREND_FLAT_BAND:
        direction, direction_label = "rising", "上升"
    elif delta <= -TREND_FLAT_BAND:
        direction, direction_label = "falling", "回落"
    else:
        direction, direction_label = "flat", "持平"

    peak = max(series, key=lambda p: p["saturation_score"])
    window_start = pd.Timestamp(series[0]["time"])
    window_end = pd.Timestamp(series[-1]["time"])

    def first_reaching(level: str) -> str | None:
        wanted = {"A"} if level == "A" else {"A", "B"}
        for point in series:
            if point["level"] in wanted:
                return point["time"]
        return None

    return {
        "segment_id": seg,
        "road_name": str(seg_df.iloc[0]["Road_Name"]),
        "sim_time": now_stamp,
        "available": True,
        "points": series,
        "measurement_count": len(series),
        "window_start": series[0]["time"],
        "window_end": series[-1]["time"],
        "window_minutes": int((window_end - window_start).total_seconds() // 60),
        "first_saturation_score": first_score,
        "current_saturation_score": current_score,
        "delta": delta,
        "delta_percentage_points": round(delta * 100, 1),
        "direction": direction,
        "direction_label": direction_label,
        "peak_saturation_score": peak["saturation_score"],
        "peak_time": peak["time"],
        "reached_level_b_at": first_reaching("B"),
        "reached_level_a_at": first_reaching("A"),
    }


def get_current_crowd_context(timestamp: str | None = None) -> dict:
    """回傳可直接提供給 Agent 的人流與漫遊資料（SOP 第 3、4、6 條判定依據）。"""
    roaming = scan_roaming(timestamp)
    stations = []
    for station in roaming["stations"]:
        stations.append({
            "基地台編號": station["bs_id"],
            "地點": station["location_name"],
            "人數": f"{station['user_count']:,} 人",
            "平均停留": f"{station['stay_time_avg']} 分鐘",
            "人流增幅": f"{station['growth_rate'] * 100:.0f}%",
            "漫遊率": station["roaming_user_pct_display"],
            "漫遊率達SOP第6條門檻": station["exceeds_sop6_threshold"],
        })
    return {
        "資料時間": roaming["data_as_of"] or roaming["query_timestamp"],
        "基地台總數": roaming["total_stations"],
        "SOP第6條多語觸發": roaming["triggered"],
        "SOP第6條觸發站點": [s["location_name"] for s in roaming["trigger_stations"]],
        "基地台狀態": stations,
    }


def get_network_context() -> dict:
    """路網靜態幾何摘要，供 Agent 回答替代路徑與相交關係問題（不隨時間變動）。"""
    segments = []
    for seg in _load_road_network():
        segments.append({
            "路段編號": seg["segment_id"],
            "路段名稱": seg["name"],
            "車流方向": seg.get("flow_direction", ""),
            "承載容量": f"{seg.get('capacity_vph', 0)} 車/小時",
            "相交路段_上游至下游": seg.get("intersections", []),
            "建議分流方向_單向": seg.get("alternatives", []),
            "周邊基地台": seg.get("nearby_stations", []),
        })
    return {"路段總數": len(segments), "路網幾何": segments}


def _percent(value: float) -> str:
    return f"{round(float(value) * 100)}%"


def calculate_optimal_route(
    incident_segment_id: str,
    timestamp: str | None = None,
    incident_location: str = "",
) -> dict:
    """
    SOP 第 2 條 (a)：從事故路段的 alternatives 篩選主疏散路徑。

    篩選條件 (逐項對齊 SOP 原文)：
      1. capacity_vph >= 1000
      2. 替代路段名稱出現在事故路段的 intersections (代表直接相交)
      3. 相交路口位於事故點上游 (依 flow_direction 與 intersections 之上游→下游排序判定)
    取通過篩選且 Saturation_Score 最低者為主疏散；位於下游之相交幹道僅列次要疏散。

    incident_location 用於定位事故點落在哪個相交路口的哪一側；未提供或無法定位時，
    退回「intersections 前半視為上游」的啟發式，並在 upstream_resolution 標明方法。

    每個 alternative 都會出現在 candidates 中（含未通過者）並附上通過或排除的理由，
    以滿足「說明排除其他候選之理由」的要求。
    """
    road_network = _load_road_network()
    traffic_df = _load_traffic_flow()

    incident_info = None
    for seg in road_network:
        if seg["segment_id"] == incident_segment_id:
            incident_info = seg
            break

    if incident_info is None:
        return {"error": f"找不到路段 {incident_segment_id}"}

    alternatives = list(incident_info.get("alternatives") or [])
    intersections = list(incident_info.get("intersections") or [])  # 上游→下游排序
    flow_direction = incident_info.get("flow_direction", "")
    incident_name = incident_info.get("name", "")
    segment_map = {s["segment_id"]: s for s in road_network}

    upstream = sop_rules.resolve_upstream(intersections, flow_direction, incident_location)

    time_df, ts = _get_time_slice(traffic_df, timestamp, key_col="Segment_ID")

    candidates: list[dict] = []
    for alt_id in alternatives:
        alt_info = segment_map.get(alt_id)
        if not alt_info:
            candidates.append({
                "segment_id": alt_id,
                "name": alt_id,
                "capacity_vph": 0,
                "saturation_score": None,
                "capacity_ok": False,
                "is_intersecting": False,
                "is_upstream": False,
                "is_congested": False,
                "tier": 0,
                "role": "excluded",
                "reason": "路網幾何資料中查無此路段",
            })
            continue

        alt_name = alt_info.get("name", alt_id)
        capacity = int(alt_info.get("capacity_vph") or 0)
        capacity_ok = capacity >= sop_rules.SOP2_MIN_CAPACITY_VPH

        is_intersecting = alt_name in intersections
        intersection_index = intersections.index(alt_name) if is_intersecting else -1
        is_upstream = is_intersecting and upstream.is_upstream(intersection_index)

        alt_flow = time_df[time_df["Segment_ID"] == alt_id]
        has_flow = not alt_flow.empty
        saturation = float(alt_flow.iloc[0]["Saturation_Score"]) if has_flow else None

        if not capacity_ok:
            tier, reason = 0, (
                f"承載容量 {capacity} 車/小時 未達 SOP 第 2 條 (1) 的 "
                f"{sop_rules.SOP2_MIN_CAPACITY_VPH} 車/小時門檻"
            )
        elif is_intersecting and is_upstream:
            tier, reason = 1, "符合 SOP 第 2 條 (1)(2)(3)：容量足夠、與事故路段直接相交且位於上游"
        elif is_intersecting:
            tier, reason = 2, (
                f"與事故路段直接相交，但相交路口位於事故點下游"
                f"（{upstream.detail}），依 SOP 第 2 條僅列次要疏散"
            )
        else:
            tier, reason = 3, (
                f"未出現在{incident_name}的 intersections 清單中，"
                "不符 SOP 第 2 條 (2) 的直接相交要求"
            )

        candidates.append({
            "segment_id": alt_id,
            "name": alt_name,
            "capacity_vph": capacity,
            "saturation_score": round(saturation, 4) if saturation is not None else None,
            "saturation_available": has_flow,
            "capacity_ok": capacity_ok,
            "is_intersecting": is_intersecting,
            "intersection_index": intersection_index,
            "is_upstream": is_upstream,
            "is_congested": bool(saturation is not None and saturation >= sop_rules.LEVEL_B_THRESHOLD),
            "tier": tier,
            "role": "excluded",
            "reason": reason,
        })

    def by_saturation(items: list[dict]) -> list[dict]:
        # 無車流資料者排在最後：沒有量測值就不該被選為主疏散
        return sorted(
            items,
            key=lambda c: (c["saturation_score"] is None, c["saturation_score"] or 0.0),
        )

    tier1 = by_saturation([c for c in candidates if c["tier"] == 1])
    tier2 = by_saturation([c for c in candidates if c["tier"] == 2])
    tier3 = by_saturation([c for c in candidates if c["tier"] == 3])

    # --- 決定主疏散與次要疏散（分層退階，絕不回傳 null） ---
    if tier1:
        primary = tier1[0]
        selection_tier = 1
        selection_reason = (
            f"依 SOP 第 2 條 (a)：{primary['name']} 容量 {primary['capacity_vph']} 車/小時、"
            f"與{incident_name}直接相交且位於事故點上游（{upstream.detail}），"
            f"為通過篩選者中飽和度最低（{_percent(primary['saturation_score'] or 0)}）"
        )
        # SOP：「位於下游之相交幹道僅列次要疏散」
        secondary = [c for c in tier2 if c["segment_id"] != primary["segment_id"]]
    elif tier2:
        primary = tier2[0]
        selection_tier = 2
        selection_reason = (
            f"退階第一層：{incident_name}的替代道路中無「相交且位於上游」者，"
            f"改取相交路段中飽和度最低的 {primary['name']}"
            f"（{_percent(primary['saturation_score'] or 0)}）"
        )
        secondary = [c for c in tier2[1:]]
    elif tier3:
        primary = tier3[0]
        selection_tier = 3
        selection_reason = (
            f"退階第二層：{incident_name}的替代道路均未列於其 intersections（依命題定義 "
            "alternatives 為單向建議，不可反推相交關係），SOP 第 2 條 (2)(3) 無可行解；"
            f"改依容量 ≥ {sop_rules.SOP2_MIN_CAPACITY_VPH} 且飽和度最低取 {primary['name']}"
            f"（{_percent(primary['saturation_score'] or 0)}）"
        )
        secondary = [c for c in tier3[1:]]
    else:
        # 最後防線：替代清單為空或全數容量不足時，改掃描全路網。
        # 優先選擇非事故路段中容量達門檻且飽和度最低者；若資料本身沒有
        # 任何達標路段，仍從非事故路段取最低飽和度者，保證不回傳空路徑。
        fallback_pool = [
            segment for segment in road_network
            if segment.get("segment_id") != incident_segment_id
            and int(segment.get("capacity_vph") or 0) >= sop_rules.SOP2_MIN_CAPACITY_VPH
        ]
        fallback_scope = "全路網容量達門檻路段"
        if not fallback_pool:
            fallback_pool = [
                segment for segment in road_network
                if segment.get("segment_id") != incident_segment_id
            ]
            fallback_scope = "全路網非事故路段"
        if not fallback_pool:
            fallback_pool = [incident_info]
            fallback_scope = "事故路段（路網無其他路段）"

        emergency_candidates = []
        for segment in fallback_pool:
            segment_id = segment.get("segment_id", incident_segment_id)
            segment_flow = time_df[time_df["Segment_ID"] == segment_id]
            has_flow = not segment_flow.empty
            saturation = (
                float(segment_flow.iloc[0]["Saturation_Score"])
                if has_flow else None
            )
            capacity = int(segment.get("capacity_vph") or 0)
            emergency_candidates.append({
                "segment_id": segment_id,
                "name": segment.get("name") or segment_id,
                "capacity_vph": capacity,
                "saturation_score": round(saturation, 4) if saturation is not None else None,
                "saturation_available": has_flow,
                "capacity_ok": capacity >= sop_rules.SOP2_MIN_CAPACITY_VPH,
                "is_intersecting": False,
                "intersection_index": -1,
                "is_upstream": False,
                "is_congested": bool(
                    saturation is not None and saturation >= sop_rules.LEVEL_B_THRESHOLD
                ),
                "tier": 0,
                "role": "excluded",
                "reason": f"Emergency Fallback：從{fallback_scope}依最低飽和度選取",
            })

        primary = by_saturation(emergency_candidates)[0]
        selection_tier = 0
        selection_reason = (
            "Emergency Fallback：事故路段沒有符合前述退階條件的替代道路，"
            f"改從{fallback_scope}選取飽和度最低的 {primary['name']}"
            f"（{_percent(primary['saturation_score'] or 0)}）"
        )
        secondary = []
        candidates.extend(emergency_candidates)

    primary["role"] = "primary"
    for candidate in secondary:
        candidate["role"] = "secondary"

    excluded = [c for c in candidates if c["role"] == "excluded"]

    congestion_note = ""
    if primary.get("is_congested"):
        # SOP 第 2 條：主疏散已壅塞仍維持該路徑，但須註明並建議併行大眾運輸
        congestion_note = (
            f"主疏散路段{primary['name']}飽和度已達 "
            f"{_percent(primary['saturation_score'] or 0)}，"
            f"依 SOP 第 2 條維持該路徑並啟動長綠燈時制"
            f"（綠燈配時 +{sop_rules.GREEN_LIGHT_EXTENSION_PCT}%），建議併行大眾運輸疏運"
        )

    return {
        "incident_segment_id": incident_segment_id,
        "incident_name": incident_name,
        "incident_location": incident_location,
        "flow_direction": flow_direction,
        "intersections": intersections,
        "query_timestamp": ts.strftime(sim_clock.TIME_FMT),
        "data_as_of": data_as_of(time_df),
        "primary_route": primary,
        "selection_tier": selection_tier,
        "selection_reason": selection_reason,
        "congestion_note": congestion_note,
        "secondary_routes": secondary,
        "excluded_routes": excluded,
        "all_candidates": candidates,
        "upstream_resolution": {
            "method": upstream.method,
            "matched_intersection": upstream.matched_intersection,
            "incident_side": upstream.incident_side,
            "downstream_side": upstream.downstream_side,
            "detail": upstream.detail,
            "upstream_intersections": [
                intersections[i] for i in sorted(upstream.upstream_indices) if i < len(intersections)
            ],
        },
    }


def segment_info(segment_id: str) -> dict:
    """路網幾何中的單一路段；查無時回傳空 dict。"""
    for seg in _load_road_network():
        if seg["segment_id"] == segment_id:
            return seg
    return {}


def segment_name(segment_id: str) -> str:
    """路段全名。CMS 文案的「<路段>」一律用這個，不要用事件的 location 描述。"""
    return segment_info(segment_id).get("name", "")


SIGNAL_SCOPE_SOP1 = "sop1_all_alternatives"
SIGNAL_SCOPE_SOP2 = "sop2_primary_only"


def build_signal_plan(
    segment_id: str,
    timestamp: str | None = None,
    duration_minutes: float | None = None,
    primary_route_id: str = "",
    scope: str | None = None,
) -> dict:
    """
    號誌配時與警力處置。兩種範圍，對應兩條不同的 SOP：

    SIGNAL_SCOPE_SOP1（城市應變觸發路段達 B/A 級）
        SOP 第 1 條：「將其替代道路 (見該路段 alternatives) 綠燈配時 +25%，
        並調度警力淨空路口」→ alternatives 全集加綠燈，並輸出警力淨空需求。
        原本只對主疏散一條加綠燈、警力完全沒輸出。

    SIGNAL_SCOPE_SOP2（非觸發路段的事故）
        SOP 第 2 條 (a)：主疏散路段已壅塞時才「啟動長綠燈時制」→ 只調整主疏散一條。

    scope 留空時依 segment_id 是否為觸發路段自動選擇。
    """
    info = segment_info(segment_id)
    if not info:
        return {"error": f"找不到路段 {segment_id}"}

    if scope is None:
        scope = (
            SIGNAL_SCOPE_SOP1
            if sop_rules.is_trigger_segment(segment_id)
            else SIGNAL_SCOPE_SOP2
        )

    traffic_df = _load_traffic_flow()
    time_df, ts = _get_time_slice(traffic_df, timestamp, key_col="Segment_ID")

    def saturation_of(seg_id: str) -> float | None:
        row = time_df[time_df["Segment_ID"] == seg_id]
        return round(float(row.iloc[0]["Saturation_Score"]), 4) if not row.empty else None

    own_saturation = saturation_of(segment_id)
    level = (
        sop_rules.assess_congestion_level(own_saturation)
        if own_saturation is not None
        else "Normal"
    )

    if scope == SIGNAL_SCOPE_SOP1:
        target_ids = list(info.get("alternatives") or [])
        sop_reference = "SOP 第 1 條：城市應變觸發路段達級別，替代道路長綠燈時制並淨空路口"
    else:
        target_ids = [primary_route_id] if primary_route_id else []
        sop_reference = "SOP 第 2 條 (a)：主疏散路段啟動長綠燈時制"

    adjustments = []
    for alt_id in target_ids:
        alt = segment_info(alt_id)
        if not alt:
            continue
        adjustments.append({
            "segment_id": alt_id,
            "road_name": alt.get("name", alt_id),
            "action": f"綠燈配時 +{sop_rules.GREEN_LIGHT_EXTENSION_PCT}%（長綠燈時制）",
            "current_saturation": saturation_of(alt_id),
            "capacity_vph": int(alt.get("capacity_vph") or 0),
            "is_primary_route": alt_id == primary_route_id,
        })

    intersections = list(info.get("intersections") or [])
    window = ""
    if duration_minutes:
        end = pd.Timestamp(ts) + pd.Timedelta(minutes=float(duration_minutes))
        window = (
            f"自 {pd.Timestamp(ts).strftime(sim_clock.TIME_FMT)} 起 "
            f"{int(round(float(duration_minutes)))} 分鐘"
            f"（至 {end.strftime(sim_clock.TIME_FMT)}），視現場狀況滾動延長"
        )

    return {
        "segment_id": segment_id,
        "road_name": info.get("name", segment_id),
        "saturation_score": own_saturation,
        "level": level,
        "level_description": sop_rules.level_description(level),
        "is_trigger_segment": sop_rules.is_trigger_segment(segment_id),
        "scope": scope,
        "sop_reference": sop_reference,
        "adjustments": adjustments,
        # 警力淨空路口是 SOP 第 1 條對觸發路段的處置，非觸發路段不套用
        "police_dispatch": (
            {
                "intersections": intersections,
                "instruction": (
                    f"調度警力淨空 {'、'.join(intersections)} 等 {len(intersections)} 處路口"
                    if intersections
                    else "該路段無相交路口資料，警力配置待現場回報"
                ),
                "staffing_note": "SOP 第 1 條未規定警力人數，不得自行估算",
            }
            if scope == SIGNAL_SCOPE_SOP1
            else None
        ),
        "duration_minutes": duration_minutes,
        "window": window,
        "query_timestamp": pd.Timestamp(ts).strftime(sim_clock.TIME_FMT),
        "data_as_of": data_as_of(time_df),
    }


def affected_segments_for_ete(
    incident_segment_id: str,
    route_result: dict | None = None,
) -> list[str]:
    """
    SOP 第 7 條「受影響路段」的唯一定義。

    = 事故路段 + 主疏散路段 + 次要疏散路段。

    採這個定義的理由：ETE 要估的是「這起事件造成的交通影響何時消退」，而分流指令
    會把車流導向主／次疏散路段，因此這幾條才是直接受影響者。原本的做法是把全市
    所有飽和度 ≥ 0.85 的路段都算進平均，會把與事件無關的壅塞稀釋進來，而且儀表板
    與建議書用了兩套不同的集合，同一事件會算出兩個 ETE。
    """
    ordered: list[str] = []

    def push(segment_id: object) -> None:
        text = str(segment_id or "").strip()
        if text and text.startswith(sop_rules.SOP2_ROAD_PREFIX) and text not in ordered:
            ordered.append(text)

    push(incident_segment_id)
    route_result = route_result if isinstance(route_result, dict) else {}
    primary = route_result.get("primary_route")
    if isinstance(primary, dict):
        push(primary.get("segment_id"))
    for candidate in route_result.get("secondary_routes") or []:
        if isinstance(candidate, dict):
            push(candidate.get("segment_id"))
    return ordered


def calculate_ete(
    severity: str,
    affected_segment_ids: list[str],
    timestamp: str | None = None,
) -> dict:
    """
    SOP 第 7 條：預計恢復時間計算。

    官方公式 (逐字對齊 emergency_traffic_sop.txt)：
      ETE_minutes = base_clearance + congestion_penalty
      - base_clearance: Critical=60, High=40, Medium=20 (分鐘)
      - congestion_penalty = (受影響路段平均 Saturation_Score - 0.5) * 60
        若結果小於 0，以 0 計。

    受影響路段一律由 affected_segments_for_ete() 決定，呼叫端不要自行組集合。
    若受影響路段完全查無車流量測，不會偷偷代入預設飽和度：壅塞懲罰以 0 計，
    並在 saturation_data_available / note 明確標示，避免產出無依據的數字。
    """
    severity_normalized = (severity or "").strip().capitalize()
    if severity_normalized not in sop_rules.ETE_BASE_CLEARANCE:
        return {
            "error": (
                f"不支援的 severity: {severity}，僅接受 "
                f"{'/'.join(sop_rules.ETE_BASE_CLEARANCE)}"
            )
        }

    base_clearance = sop_rules.ETE_BASE_CLEARANCE[severity_normalized]
    requested = [str(s) for s in (affected_segment_ids or [])]

    traffic_df = _load_traffic_flow()
    time_df, ts = _get_time_slice(traffic_df, timestamp, key_col="Segment_ID")
    affected_df = time_df[time_df["Segment_ID"].isin(requested)]

    has_data = not affected_df.empty
    if has_data:
        avg_saturation = float(affected_df["Saturation_Score"].mean())
        congestion_penalty = round(
            max(
                0.0,
                (avg_saturation - sop_rules.ETE_SATURATION_BASELINE)
                * sop_rules.ETE_SATURATION_FACTOR,
            ),
            2,
        )
        note = ""
    else:
        avg_saturation = None
        congestion_penalty = 0.0
        note = "受影響路段查無車流量測，壅塞懲罰以 0 計，ETE 僅採基礎清除時間"

    breakdown = []
    for segment_id in requested:
        row = affected_df[affected_df["Segment_ID"] == segment_id]
        if row.empty:
            breakdown.append({
                "segment_id": segment_id,
                "road_name": "",
                "saturation_score": None,
                "available": False,
            })
            continue
        record = row.iloc[0]
        breakdown.append({
            "segment_id": segment_id,
            "road_name": record["Road_Name"],
            "saturation_score": round(float(record["Saturation_Score"]), 4),
            "available": True,
        })

    return {
        "severity": severity_normalized,
        "base_clearance_minutes": base_clearance,
        "avg_saturation_score": round(avg_saturation, 4) if avg_saturation is not None else None,
        "congestion_penalty_minutes": congestion_penalty,
        "ete_minutes": round(base_clearance + congestion_penalty, 2),
        "formula": sop_rules.ETE_FORMULA,
        "saturation_data_available": has_data,
        "note": note,
        "query_timestamp": ts.strftime(sim_clock.TIME_FMT),
        "data_as_of": data_as_of(affected_df),
        "affected_segment_ids": requested,
        "affected_segments": breakdown,
        "affected_segments_found": len(affected_df),
        "affected_segments_requested": len(requested),
    }


# ---------------------------------------------------------------------------
# SOP 第 6 條 — 漫遊率
# ---------------------------------------------------------------------------


def _station_record(record: pd.Series) -> dict:
    roaming_val = record["Roaming_User_Pct"]
    if isinstance(roaming_val, str):
        roaming_pct = float(roaming_val.replace("%", "").strip()) / 100
    else:
        roaming_pct = float(roaming_val)

    growth_val = record.get("Growth_Rate", 0)
    if isinstance(growth_val, str):
        growth_val = float(growth_val.replace("%", "").strip())

    return {
        "bs_id": record["BS_ID"],
        "location_name": record["Location_Name"],
        "user_count": int(round(float(record["User_Count"]))),
        "stay_time_avg": int(round(float(record.get("Stay_Time_Avg", 0) or 0))),
        "growth_rate": round(float(growth_val or 0), 4),
        "roaming_user_pct": round(roaming_pct, 4),
        "roaming_user_pct_display": f"{roaming_pct * 100:.1f}%",
        "exceeds_sop6_threshold": roaming_pct >= sop_rules.SOP6_ROAMING_THRESHOLD,
        "data_as_of": pd.Timestamp(record["Timestamp"]).strftime(sim_clock.TIME_FMT),
    }


def check_roaming_rate(bs_id: str, timestamp: str | None = None) -> dict:
    """查詢單一基地台漫遊率。注意 SOP 第 6 條的觸發判定請用 scan_roaming()。"""
    crowd_df = _load_crowd_density()
    bs_df = crowd_df[crowd_df["BS_ID"] == bs_id]
    if bs_df.empty:
        return {"error": f"找不到基地台 {bs_id}"}

    time_slice, ts = _get_time_slice(bs_df, timestamp, key_col="BS_ID")
    if time_slice.empty:
        return {"error": f"基地台 {bs_id} 在指定時間無資料"}

    payload = _station_record(time_slice.iloc[0])
    payload["query_timestamp"] = pd.Timestamp(ts).strftime(sim_clock.TIME_FMT)
    # 保留舊欄位名讓既有呼叫端不致失效，但語意已改為「本站是否超標」
    payload["trigger_sop6_multilingual"] = payload["exceeds_sop6_threshold"]
    return payload


def crowd_snapshot(timestamp: str | None = None) -> dict:
    """
    查詢時間當下的全基地台人流切片。

    切片語意與車流一致（統一由 _get_time_slice 決定 interpolate / asof / exact），
    所以儀表板顯示的數字與 SOP 判定用的數字保證同源。
    """
    crowd_df = _load_crowd_density()
    time_df, ts = _get_time_slice(crowd_df, timestamp, key_col="BS_ID")
    stations = [_station_record(row) for _, row in time_df.iterrows()]
    stations.sort(key=lambda s: s["bs_id"])
    return {
        "query_timestamp": pd.Timestamp(ts).strftime(sim_clock.TIME_FMT),
        "data_as_of": data_as_of(time_df),
        "total_stations": len(stations),
        "stations": stations,
    }


def scan_roaming(timestamp: str | None = None) -> dict:
    """
    SOP 第 6 條觸發判定：掃描**全部**基地台，任一站點 Roaming_User_Pct >= 30% 即觸發。

    原本的實作只檢查事故路段的 nearby_stations，範圍比 SOP 原文窄。實測在三個官方
    事件的發生時間，周邊基地台都低於 30%，但全市的台北101廣場與 ATT4FUN 周邊早已
    超標，導致多語通報永遠不會觸發。此函式是 SOP 第 6 條唯一的判定入口。
    """
    snapshot = crowd_snapshot(timestamp)
    stations = snapshot["stations"]
    triggers = [s for s in stations if s["exceeds_sop6_threshold"]]
    triggers.sort(key=lambda s: s["roaming_user_pct"], reverse=True)

    return {
        "query_timestamp": snapshot["query_timestamp"],
        "data_as_of": snapshot["data_as_of"],
        "threshold": sop_rules.SOP6_ROAMING_THRESHOLD,
        "threshold_display": f"{sop_rules.SOP6_ROAMING_THRESHOLD * 100:.0f}%",
        "triggered": bool(triggers),
        "scope": "全資料集所有基地台",
        "total_stations": len(stations),
        "trigger_stations": triggers,
        "stations": stations,
        "languages": list(
            sop_rules.SOP6_LANGUAGES if triggers else sop_rules.SOP6_DEFAULT_LANGUAGES
        ),
    }


# ---------------------------------------------------------------------------
# SOP 第 3、4 條 — 人流門檻與歷史峰值
# ---------------------------------------------------------------------------


def station_history(bs_id: str, timestamp: str | None = None) -> dict:
    """
    截至查詢時間的單站人流歷史，含歷史峰值 — 供 SOP 第 4 條「峰值曾達 >= 30,000」判定。

    峰值本質上是累積狀態，一律只看 <= 查詢時間的實際量測，不套用插值，
    也不會碰到查詢時間之後的資料。
    """
    crowd_df = _load_crowd_density()
    bs_df = crowd_df[crowd_df["BS_ID"] == bs_id]
    if bs_df.empty:
        return {"error": f"找不到基地台 {bs_id}"}

    ts = sim_clock.resolve(timestamp)
    history = bs_df[bs_df["Timestamp"] <= ts].sort_values("Timestamp")
    if history.empty:
        return {
            "bs_id": bs_id,
            "location_name": str(bs_df.iloc[0]["Location_Name"]),
            "query_timestamp": pd.Timestamp(ts).strftime(sim_clock.TIME_FMT),
            "samples": 0,
            "peak_user_count": None,
            "peak_at": None,
            "current_user_count": None,
            "current_growth_rate": None,
            "data_as_of": None,
        }

    peak_row = history.loc[history["User_Count"].idxmax()]
    latest = history.iloc[-1]
    growth_val = latest["Growth_Rate"]
    if isinstance(growth_val, str):
        growth_val = float(growth_val.replace("%", "").strip())

    return {
        "bs_id": bs_id,
        "location_name": str(latest["Location_Name"]),
        "query_timestamp": pd.Timestamp(ts).strftime(sim_clock.TIME_FMT),
        "samples": int(len(history)),
        "peak_user_count": int(peak_row["User_Count"]),
        "peak_at": pd.Timestamp(peak_row["Timestamp"]).strftime(sim_clock.TIME_FMT),
        "current_user_count": int(latest["User_Count"]),
        "current_growth_rate": round(float(growth_val or 0), 4),
        "data_as_of": pd.Timestamp(latest["Timestamp"]).strftime(sim_clock.TIME_FMT),
    }


def station_reading(bs_id: str, timestamp: str | None = None) -> dict | None:
    """查詢時間當下的單站人流讀值（依 SIM_DATA_MODE 切片），查無資料回傳 None。"""
    crowd_df = _load_crowd_density()
    bs_df = crowd_df[crowd_df["BS_ID"] == bs_id]
    if bs_df.empty:
        return None
    time_slice, ts = _get_time_slice(bs_df, timestamp, key_col="BS_ID")
    if time_slice.empty:
        return None
    payload = _station_record(time_slice.iloc[0])
    payload["query_timestamp"] = pd.Timestamp(ts).strftime(sim_clock.TIME_FMT)
    return payload


def evaluate_crowd_scenario(
    bs_id: str,
    timestamp: str | None = None,
    user_count: int | None = None,
    growth_rate: float | None = None,
    roaming_user_pct: float | None = None,
) -> dict:
    """以當下讀值為基準，套用使用者明示的人流假設並做確定性 SOP 判定。

    未提供的欄位沿用資料集當下讀值，回傳值會明列哪些欄位是假設、哪些欄位沿用，
    避免 LLM 自行推導人流增幅或漫遊率。所有門檻只取自 sop_rules。
    """
    baseline = station_reading(bs_id, timestamp)
    if not baseline:
        return {"error": f"查無基地台 {bs_id}", "bs_id": bs_id}

    scenario = {
        "user_count": int(baseline.get("user_count") or 0),
        "growth_rate": float(baseline.get("growth_rate") or 0),
        "roaming_user_pct": float(baseline.get("roaming_user_pct") or 0),
    }
    provided: list[str] = []
    if user_count is not None:
        scenario["user_count"] = max(0, int(user_count))
        provided.append("user_count")
    if growth_rate is not None:
        scenario["growth_rate"] = float(growth_rate)
        provided.append("growth_rate")
    if roaming_user_pct is not None:
        value = float(roaming_user_pct)
        # 對外契約一律使用 0~1；拒絕把百分數 30 當成 30 倍。
        if not 0 <= value <= 1:
            return {"error": "漫遊率必須使用 0 到 1，例如 30% 請輸入 0.3"}
        scenario["roaming_user_pct"] = value
        provided.append("roaming_user_pct")

    checks: list[dict] = []
    triggered_numbers: list[int] = []

    if bs_id == sop_rules.SOP3_STATION:
        growth_hit = scenario["growth_rate"] > sop_rules.SOP3_GROWTH_THRESHOLD
        count_hit = scenario["user_count"] > sop_rules.SOP3_USER_COUNT_THRESHOLD
        triggered = growth_hit or count_hit
        reasons = []
        if growth_hit:
            reasons.append(
                f"人流增幅 {scenario['growth_rate']:.0%} 超過 "
                f"{sop_rules.SOP3_GROWTH_THRESHOLD:.0%}"
            )
        if count_hit:
            reasons.append(
                f"站內人數 {scenario['user_count']:,} 人超過 "
                f"{sop_rules.SOP3_USER_COUNT_THRESHOLD:,} 人"
            )
        checks.append({
            "sop_number": 3,
            "triggered": triggered,
            "reason": "、".join(reasons) if reasons else "人數與人流增幅均未達門檻",
            "actions": list(sop_rules.SOP3_ACTIONS) if triggered else [],
        })
        if triggered:
            triggered_numbers.append(3)

    # 多語判定以全資料集掃描為基準；若本情境明示更高漫遊率，再合併該假設。
    roaming_scan = scan_roaming(timestamp)
    roaming_triggered = bool(roaming_scan.get("triggered")) or (
        roaming_user_pct is not None
        and scenario["roaming_user_pct"] >= sop_rules.SOP6_ROAMING_THRESHOLD
    )
    roaming_reason = (
        "全資料集已有基地台達漫遊率門檻"
        if roaming_scan.get("triggered")
        else (
            f"假設漫遊率 {scenario['roaming_user_pct']:.0%} 已達 "
            f"{sop_rules.SOP6_ROAMING_THRESHOLD:.0%}"
            if roaming_triggered
            else "全資料集與本情境均未達漫遊率門檻"
        )
    )
    checks.append({
        "sop_number": 6,
        "triggered": roaming_triggered,
        "reason": roaming_reason,
        "languages": list(
            sop_rules.SOP6_LANGUAGES
            if roaming_triggered
            else sop_rules.SOP6_DEFAULT_LANGUAGES
        ),
    })
    if roaming_triggered:
        triggered_numbers.append(6)

    return {
        "bs_id": bs_id,
        "location_name": baseline.get("location_name", bs_id),
        "query_timestamp": baseline.get("query_timestamp"),
        "data_as_of": baseline.get("data_as_of"),
        "baseline": {
            "user_count": int(baseline.get("user_count") or 0),
            "growth_rate": float(baseline.get("growth_rate") or 0),
            "roaming_user_pct": float(baseline.get("roaming_user_pct") or 0),
        },
        "scenario": scenario,
        "provided_hypotheses": provided,
        "unchanged_from_baseline": [
            field for field in ("user_count", "growth_rate", "roaming_user_pct")
            if field not in provided
        ],
        "triggered_numbers": triggered_numbers,
        "checks": checks,
        "note": "未明示的情境欄位沿用當下資料，不做推測",
    }


def calculate_answer_confidence(
    *,
    prompt: str,
    response: str,
    current_time: str,
    model_ok: bool,
    tools_used: list[str] | None = None,
    cited_clause_numbers: list[int] | None = None,
    data_as_of: str | None = None,
    history_available: bool = False,
    tool_error: bool = False,
    tool_truncated: bool = False,
) -> dict:
    """依可稽核證據計算 What-if 回覆信心值，禁止交由 LLM 自評。"""
    if not model_ok:
        return {
            "score": 5,
            "level": "low",
            "label": "低信心",
            "evidence_sources": [],
            "reasons": ["AI 模型或服務未正常回應，無法建立決策證據鏈"],
        }

    score = 30
    positive: list[str] = ["AI 模型已正常完成回覆"]
    concerns: list[str] = []
    tools = list(dict.fromkeys(tools_used or []))
    clauses = list(dict.fromkeys(cited_clause_numbers or []))
    source_map = {
        "lookup_sop_clause": ("SOP 條文",),
        "traffic_status": ("即時車流資料",),
        "crowd_status": ("基地台人流資料", "SOP 條文"),
        "sop_trigger_status": ("即時車流資料", "基地台人流資料", "SOP 條文"),
        "evacuation_route": ("即時車流資料", "路網拓樸", "SOP 條文"),
        "recovery_time": ("即時車流資料", "路網拓樸", "SOP 條文"),
        "signal_plan": ("即時車流資料", "路網拓樸", "SOP 條文"),
        "station_detail": ("基地台人流資料",),
        "network_geometry": ("路網拓樸",),
    }
    evidence_sources: list[str] = []
    for tool_name in tools:
        for source in source_map.get(tool_name, ("確定性後端資料",)):
            if source not in evidence_sources:
                evidence_sources.append(source)

    if data_as_of:
        score += 20
        positive.append(f"已對齊資料時間 {data_as_of}")

    if tools:
        score += 30 + min(5, max(0, len(tools) - 1) * 2)
        source_text = "、".join(evidence_sources) or "確定性後端資料"
        positive.append(f"本輪使用 {len(tools)} 項工具核對{source_text}")
    elif history_available and any(
        marker in (prompt or "") for marker in ("延續", "上一題", "剛才", "前述", "上述")
    ):
        score += 25
        evidence_sources.append("前輪已驗證證據")
        positive.append("本輪明確沿用前一輪已驗證的工具證據")
    else:
        score -= 20
        concerns.append("本輪未使用確定性工具，也未明確沿用前輪證據")

    policy_question = any(
        marker in (prompt or "")
        for marker in ("SOP", "條款", "觸發", "應變", "措施", "處置", "決策")
    )
    if clauses:
        score += 8
        if "SOP 條文" not in evidence_sources:
            evidence_sources.append("SOP 條文")
        positive.append(f"附有 {len(clauses)} 條 SOP 原文依據")
    elif policy_question:
        score -= 10
        concerns.append("題目涉及應變規則，但回覆未引用 SOP 原文")

    if all(label in (response or "") for label in ("判斷：", "建議：", "行動指令：")):
        score += 5

    identifiers = set(re.findall(r"\b(?:RD|BS)_[A-Z0-9_]+\b", prompt or ""))
    unknown_identifiers = []
    for identifier in sorted(identifiers):
        if identifier.startswith("RD_") and not segment_info(identifier):
            unknown_identifiers.append(identifier)
        elif identifier.startswith("BS_") and station_reading(identifier, current_time) is None:
            unknown_identifiers.append(identifier)
    if unknown_identifiers:
        score -= 30
        concerns.append("查無題目中的資料實體：" + "、".join(unknown_identifiers))

    future_times = []
    try:
        now = pd.Timestamp(current_time)
        for date_text in re.findall(r"\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?", prompt or ""):
            parsed = pd.Timestamp(date_text)
            if parsed > now:
                future_times.append(date_text)
    except (TypeError, ValueError):
        future_times = []
    if future_times:
        score -= 30
        concerns.append("題目要求的時間晚於目前可用資料：" + "、".join(future_times))

    uncertainty_markers = (
        "查無資料", "無法判定", "無法取得", "資料不足", "不得推測", "無紀錄",
    )
    if any(marker in (response or "") for marker in uncertainty_markers):
        score -= 15
        concerns.append("回覆明示存在資料缺口或不可推測範圍")
    if tool_error:
        score -= 40
        concerns.append("確定性工具回傳錯誤或查無資料")
    if tool_truncated:
        score -= 10
        concerns.append("工具證據過長而被截斷")

    score = max(5, min(98, int(round(score))))
    if score >= 85:
        level, label = "high", "高信心"
    elif score >= 60:
        level, label = "medium", "中信心"
    else:
        level, label = "low", "低信心"

    reasons = positive[:3] + concerns[:3]
    return {
        "score": score,
        "level": level,
        "label": label,
        "evidence_sources": evidence_sources,
        "reasons": reasons,
    }
