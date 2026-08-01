"""
交通數學計算模組 — 嚴格依據 emergency_traffic_sop.txt 第 2 條與第 7 條。

⚠️ 全局約束：所有數值計算只在此模組執行，Agent 禁止自行推算。
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pandas as pd

from backend import sim_clock
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
        segments.append({
            "路段編號": row["Segment_ID"],
            "路段名稱": row["Road_Name"],
            "飽和度": f"{round(float(row['Saturation_Score']) * 100)}%",
            "平均車速": f"{float(row['Avg_Speed']):g} 公里/小時",
            "車流量": f"{int(row['Vehicle_Count'])} 輛",
            "車道狀態": row["Lane_Status"],
        })
    return {
        "資料時間": data_timestamp,
        "路段總數": len(segments),
        "路段狀態": segments,
    }


def calculate_optimal_route(incident_segment_id: str, timestamp: str | None = None) -> dict:
    """
    SOP 第 2 條：從事故路段的 alternatives 篩選主疏散路徑。

    篩選邏輯 (嚴格對齊 SOP 原文)：
      1. capacity_vph >= 1000
      2. 替代路段名稱出現在事故路段的 intersections (代表直接相交)
      3. 位於上游 (intersections 陣列中，排序在前者為上游)

    Fallback 機制：
      - 若無上游路段符合 → 取所有相交路段中飽和度最低者
      - 若無相交路段符合 → 取所有 alternatives 中 capacity>=1000 且飽和度最低者
      - 絕不回傳 null
    """
    road_network = _load_road_network()
    traffic_df = _load_traffic_flow()

    # 找事故路段
    incident_info = None
    for seg in road_network:
        if seg["segment_id"] == incident_segment_id:
            incident_info = seg
            break

    if incident_info is None:
        return {"error": f"找不到路段 {incident_segment_id}"}

    alternatives = incident_info["alternatives"]
    intersections = incident_info["intersections"]  # 上游→下游排序
    segment_map = {s["segment_id"]: s for s in road_network}

    time_df, ts = _get_time_slice(traffic_df, timestamp, key_col="Segment_ID")

    # 為每個 alternative 計算資訊
    all_candidates = []
    for alt_id in alternatives:
        alt_info = segment_map.get(alt_id)
        if not alt_info:
            continue

        # 條件 1: capacity >= 1000
        if alt_info["capacity_vph"] < 1000:
            continue

        alt_name = alt_info["name"]

        # 條件 2: 替代路段名稱出現在事故路段的 intersections
        is_intersecting = alt_name in intersections

        # 條件 3: 上游判定 (intersections 陣列前半為上游)
        is_upstream = False
        if is_intersecting:
            midpoint = len(intersections) / 2
            idx = intersections.index(alt_name)
            is_upstream = idx < midpoint

        # 取飽和度
        alt_flow = time_df[time_df["Segment_ID"] == alt_id]
        saturation = float(alt_flow.iloc[0]["Saturation_Score"]) if not alt_flow.empty else 0.5

        all_candidates.append({
            "segment_id": alt_id,
            "name": alt_name,
            "capacity_vph": alt_info["capacity_vph"],
            "saturation_score": round(saturation, 4),
            "is_intersecting": is_intersecting,
            "is_upstream": is_upstream,
            "is_congested": saturation >= 0.85,
        })

    # --- 分層篩選 (絕不回傳 null) ---

    # 第一層：完全符合 SOP (上游 + 相交 + capacity>=1000)
    tier1 = [c for c in all_candidates if c["is_upstream"] and c["is_intersecting"]]
    tier1.sort(key=lambda x: x["saturation_score"])

    # 第二層 Fallback：相交但位於下游
    tier2 = [c for c in all_candidates if c["is_intersecting"] and not c["is_upstream"]]
    tier2.sort(key=lambda x: x["saturation_score"])

    # 第三層 Fallback：任何 capacity>=1000 的 alternative
    tier3 = [c for c in all_candidates if not c["is_intersecting"]]
    tier3.sort(key=lambda x: x["saturation_score"])

    # 決定主疏散
    if tier1:
        primary = tier1[0]
        selection_reason = "SOP 第 2 條：上游相交路段，飽和度最低"
    elif tier2:
        primary = tier2[0]
        selection_reason = "Fallback：下游相交路段，飽和度最低"
    elif tier3:
        primary = tier3[0]
        selection_reason = "Fallback：替代路段中容量足夠且飽和度最低"
    else:
        # 極端情況：所有 alternatives 容量都 < 1000
        primary = {
            "segment_id": alternatives[0] if alternatives else "",
            "name": segment_map.get(alternatives[0], {}).get("name", "") if alternatives else "",
            "capacity_vph": 0,
            "saturation_score": 1.0,
            "is_intersecting": False,
            "is_upstream": False,
            "is_congested": True,
        }
        selection_reason = "緊急 Fallback：無符合條件路段，建議併行大眾運輸"

    # 壅塞標記
    congestion_note = ""
    if primary["is_congested"]:
        congestion_note = "主疏散路段已壅塞，維持該路徑並啟動長綠燈時制，建議併行大眾運輸"

    return {
        "incident_segment_id": incident_segment_id,
        "incident_name": incident_info["name"],
        "query_timestamp": ts.strftime(sim_clock.TIME_FMT),
        "data_as_of": data_as_of(time_df),
        "primary_route": primary,
        "selection_reason": selection_reason,
        "congestion_note": congestion_note,
        "secondary_routes": tier2 if tier1 else tier3,
        "all_candidates": all_candidates,
    }


def calculate_ete(severity: str, affected_segment_ids: list[str], timestamp: str | None = None) -> dict:
    """
    SOP 第 7 條：預計恢復時間計算。

    官方公式 (逐字對齊 emergency_traffic_sop.txt)：
      ETE_minutes = base_clearance + congestion_penalty
      - base_clearance: Critical=60, High=40, Medium=20 (分鐘)
      - congestion_penalty = (受影響路段平均 Saturation_Score - 0.5) * 60
        若結果小於 0，以 0 計。
    """
    base_map = {"Critical": 60, "High": 40, "Medium": 20}
    severity_normalized = severity.strip().capitalize()
    if severity_normalized not in base_map:
        return {"error": f"不支援的 severity: {severity}，僅接受 Critical/High/Medium"}

    base_clearance = base_map[severity_normalized]
    traffic_df = _load_traffic_flow()
    time_df, ts = _get_time_slice(traffic_df, timestamp, key_col="Segment_ID")

    affected_df = time_df[time_df["Segment_ID"].isin(affected_segment_ids)]
    avg_saturation = float(affected_df["Saturation_Score"].mean()) if not affected_df.empty else 0.5

    # 官方公式
    congestion_penalty = max(0, (avg_saturation - 0.5) * 60)
    congestion_penalty = round(congestion_penalty, 2)
    ete_minutes = round(base_clearance + congestion_penalty, 2)

    return {
        "severity": severity_normalized,
        "base_clearance_minutes": base_clearance,
        "avg_saturation_score": round(avg_saturation, 4),
        "congestion_penalty_minutes": congestion_penalty,
        "ete_minutes": ete_minutes,
        "formula": "ETE = base_clearance + max(0, (avg_saturation - 0.5) × 60)",
        "query_timestamp": ts.strftime(sim_clock.TIME_FMT),
        "data_as_of": data_as_of(affected_df),
        "affected_segments_found": len(affected_df),
        "affected_segments_requested": len(affected_segment_ids),
    }


def check_roaming_rate(bs_id: str, timestamp: str | None = None) -> dict:
    """查詢指定基地台漫遊率 (SOP 第 6 條判定用)。"""
    crowd_df = _load_crowd_density()
    bs_df = crowd_df[crowd_df["BS_ID"] == bs_id]
    if bs_df.empty:
        return {"error": f"找不到基地台 {bs_id}"}

    time_slice, ts = _get_time_slice(bs_df, timestamp, key_col="BS_ID")
    if time_slice.empty:
        return {"error": f"基地台 {bs_id} 在指定時間無資料"}

    record = time_slice.iloc[0]
    roaming_val = record["Roaming_User_Pct"]
    if isinstance(roaming_val, str):
        roaming_pct = float(roaming_val.replace("%", "").strip()) / 100
    else:
        roaming_pct = float(roaming_val)

    return {
        "bs_id": bs_id,
        "location_name": record["Location_Name"],
        "roaming_user_pct": round(roaming_pct, 4),
        "roaming_user_pct_display": f"{roaming_pct * 100:.1f}%",
        "trigger_sop6_multilingual": roaming_pct >= 0.30,
        "user_count": int(record["User_Count"]),
        "query_timestamp": pd.Timestamp(ts).strftime(sim_clock.TIME_FMT),
        "data_as_of": data_as_of(time_slice),
    }
