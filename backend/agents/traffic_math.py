"""
交通數學計算模組 — 嚴格依據 emergency_traffic_sop.txt 第 2 條與第 7 條。

⚠️ 全局約束：所有數值計算只在此模組執行，Agent 禁止自行推算。
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"

TRAFFIC_FLOW_CSV = DATA_DIR / "city_traffic_flow.csv"
ROAD_NETWORK_JSON = DATA_DIR / "road_network_geometry.json"
CROWD_DENSITY_CSV = DATA_DIR / "signaling_crowd_density.csv"


def _load_traffic_flow() -> pd.DataFrame:
    df = pd.read_csv(TRAFFIC_FLOW_CSV, parse_dates=["Timestamp"])
    if df["Saturation_Score"].dtype == object:
        df["Saturation_Score"] = df["Saturation_Score"].str.rstrip("%").astype(float)
        df.loc[df["Saturation_Score"] > 1, "Saturation_Score"] /= 100
    return df


def _load_road_network() -> list[dict]:
    with open(ROAD_NETWORK_JSON, encoding="utf-8") as f:
        return json.load(f)


def _load_crowd_density() -> pd.DataFrame:
    df = pd.read_csv(CROWD_DENSITY_CSV, parse_dates=["Timestamp"])
    if df["Roaming_User_Pct"].dtype == object:
        df["Roaming_User_Pct"] = df["Roaming_User_Pct"].str.rstrip("%").astype(float) / 100
    return df


def _get_time_slice(df: pd.DataFrame, timestamp: str | None) -> tuple[pd.DataFrame, pd.Timestamp]:
    """取得指定時間或最接近時間的資料切片。"""
    if timestamp:
        ts = pd.Timestamp(timestamp)
    else:
        ts = df["Timestamp"].max()

    time_df = df[df["Timestamp"] == ts]
    if time_df.empty:
        closest_idx = (df["Timestamp"] - ts).abs().argsort().iloc[0]
        ts = df.iloc[closest_idx]["Timestamp"]
        time_df = df[df["Timestamp"] == ts]
    return time_df, ts


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

    time_df, ts = _get_time_slice(traffic_df, timestamp)

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
        "query_timestamp": ts.strftime("%Y-%m-%d %H:%M"),
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
    time_df, ts = _get_time_slice(traffic_df, timestamp)

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
        "query_timestamp": ts.strftime("%Y-%m-%d %H:%M"),
        "affected_segments_found": len(affected_df),
        "affected_segments_requested": len(affected_segment_ids),
    }


def check_roaming_rate(bs_id: str, timestamp: str | None = None) -> dict:
    """查詢指定基地台漫遊率 (SOP 第 6 條判定用)。"""
    crowd_df = _load_crowd_density()
    bs_df = crowd_df[crowd_df["BS_ID"] == bs_id]
    if bs_df.empty:
        return {"error": f"找不到基地台 {bs_id}"}

    time_slice, ts = _get_time_slice(bs_df, timestamp)
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
        "query_timestamp": pd.Timestamp(ts).strftime("%Y-%m-%d %H:%M"),
    }
