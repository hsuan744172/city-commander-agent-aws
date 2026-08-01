"""
SOP 判定規則的單一來源 — 逐字對應 data/emergency_traffic_sop.txt。

這個模組只放「規則本身」：門檻、常數、事件分類、上下游判定。
不做資料讀取，也不做數值計算（數值一律在 traffic_math）。

之所以集中在這裡：門檻值原本散落在 policy.py、main.py、三個前端元件裡，
SOP 一改就會漂移。現在後端只有這一份，前端也由 API 取得同一份門檻。
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# SOP 第 1 條 — 交通擁塞級別判定
# ---------------------------------------------------------------------------

LEVEL_B_THRESHOLD = 0.85          # B 級 (壅擠 / 黃燈)
LEVEL_A_THRESHOLD = 0.95          # A 級 (癱瘓 / 紅燈)

# 「城市應變觸發路段」— 只有這兩段達級別才啟動長綠燈時制與替代路徑引導。
# 其餘 13 段的分級僅用於 Dashboard 紅黃燈顯示。
SOP1_TRIGGER_SEGMENTS: tuple[str, ...] = ("RD_TPE_001", "RD_TPE_002")

GREEN_LIGHT_EXTENSION_PCT = 25    # 長綠燈時制：替代道路綠燈配時 +25%

# ---------------------------------------------------------------------------
# SOP 第 2 條 — 車禍與路障應變
# ---------------------------------------------------------------------------

SOP2_STATUSES = frozenset({"Closed", "Blocked", "Restricted"})
SOP2_SEVERITIES = frozenset({"High", "Critical"})
SOP2_MIN_CAPACITY_VPH = 1000
SOP2_ROAD_PREFIX = "RD_"

# ---------------------------------------------------------------------------
# SOP 第 3 條 — 捷運與接駁分流
# ---------------------------------------------------------------------------

SOP3_STATION = "BS_MRT_BL17"          # 捷運國父紀念館站
SOP3_RELIEF_STATION = "BS_MRT_BL18"   # 引導群眾步行至捷運市政府站
SOP3_GROWTH_THRESHOLD = 0.30          # Growth_Rate > 0.30
SOP3_USER_COUNT_THRESHOLD = 25000     # 或 User_Count > 25,000
SOP3_ACTIONS: tuple[str, ...] = (
    "建議臺北捷運公司於國父紀念館站啟動過站不停",
    "通知公車處調度接駁專車疏運",
    "引導群眾步行至捷運市政府站（BS_MRT_BL18）分流",
    "協調警力維持站體與出口秩序",
)

# ---------------------------------------------------------------------------
# SOP 第 4 條 — 大巨蛋散場啟動
# ---------------------------------------------------------------------------

SOP4_STATION = "BS_TPE_DOME"          # 大巨蛋場館內
SOP4_PEAK_THRESHOLD = 30000           # 歷史峰值曾達 >= 30,000
SOP4_DECLINE_THRESHOLD = -0.20        # 且當前 Growth_Rate <= -0.20

# ---------------------------------------------------------------------------
# SOP 第 5 條 — 號誌故障應變
# ---------------------------------------------------------------------------

SIGNAL_FAILURE_TYPE = "Power_Failure"
# 只認明確描述號誌的字樣。原本 policy.py 另外收了裸關鍵字「故障」，
# 會讓任何含「故障」的事件都判成號誌故障，這裡收斂。
SIGNAL_FAILURE_KEYWORDS: tuple[str, ...] = ("號誌失效", "號誌故障")
SOP5_POLICE_PER_INTERSECTION = 2

# ---------------------------------------------------------------------------
# SOP 第 6 條 — 數位通報與多語化
# ---------------------------------------------------------------------------

# 原文：「觸發：任一基地台 Roaming_User_Pct >= 30%」
# 判定範圍是「全資料集任一基地台」，不是事故路段周邊基地台。
SOP6_ROAMING_THRESHOLD = 0.30
SOP6_LANGUAGES: tuple[str, ...] = ("zh-TW", "en", "ja", "ko")
SOP6_DEFAULT_LANGUAGES: tuple[str, ...] = ("zh-TW",)

# ---------------------------------------------------------------------------
# SOP 第 7 條 — 預計恢復時間 (ETE)
# ---------------------------------------------------------------------------

ETE_BASE_CLEARANCE: dict[str, int] = {"Critical": 60, "High": 40, "Medium": 20}
ETE_SATURATION_BASELINE = 0.5
ETE_SATURATION_FACTOR = 60
ETE_FORMULA = "ETE = base_clearance + max(0, (avg_saturation - 0.5) × 60)"

# ---------------------------------------------------------------------------
# 通用
# ---------------------------------------------------------------------------

TIME_FMT = "%Y-%m-%d %H:%M"       # SOP 第 6 條：時間格式統一
STATION_PREFIX = "BS_"


def assess_congestion_level(saturation_score: float) -> str:
    """SOP 第 1 條分級。全系統唯一實作。"""
    score = float(saturation_score or 0)
    if score >= LEVEL_A_THRESHOLD:
        return "A"
    if score >= LEVEL_B_THRESHOLD:
        return "B"
    return "Normal"


def level_description(level: str) -> str:
    return {"A": "A 級癱瘓", "B": "B 級壅擠"}.get(level, "正常")


def is_trigger_segment(segment_id: str) -> bool:
    """是否為 SOP 第 1 條的城市應變觸發路段。"""
    return (segment_id or "") in SOP1_TRIGGER_SEGMENTS


def police_required(intersection_count: int) -> int:
    """SOP 第 5 條：每路口 2 人。"""
    return max(0, int(intersection_count)) * SOP5_POLICE_PER_INTERSECTION


def thresholds_payload() -> dict:
    """提供給前端的門檻表，避免前端自己寫死 0.85 / 0.95 / 30%。"""
    return {
        "level_b": LEVEL_B_THRESHOLD,
        "level_a": LEVEL_A_THRESHOLD,
        "sop1_trigger_segments": list(SOP1_TRIGGER_SEGMENTS),
        "green_light_extension_pct": GREEN_LIGHT_EXTENSION_PCT,
        "sop2_min_capacity_vph": SOP2_MIN_CAPACITY_VPH,
        "sop3_growth": SOP3_GROWTH_THRESHOLD,
        "sop3_user_count": SOP3_USER_COUNT_THRESHOLD,
        "sop3_station": SOP3_STATION,
        "sop3_relief_station": SOP3_RELIEF_STATION,
        "sop4_station": SOP4_STATION,
        "sop4_peak": SOP4_PEAK_THRESHOLD,
        "sop4_decline": SOP4_DECLINE_THRESHOLD,
        "sop6_roaming": SOP6_ROAMING_THRESHOLD,
        "ete_base_clearance": dict(ETE_BASE_CLEARANCE),
        "ete_formula": ETE_FORMULA,
    }


# ---------------------------------------------------------------------------
# 事件分類 — 原本在 architect / policy / comms 各寫一份且條件不一致
# ---------------------------------------------------------------------------

ROAD_INCIDENT = "road"
CROWD_INCIDENT = "crowd"
SIGNAL_FAILURE = "signal"
UNKNOWN_INCIDENT = "unknown"


@dataclass(frozen=True, slots=True)
class IncidentClass:
    """單一事件的分類結果。所有下游模組都用這個，不再各自判斷。"""

    kind: str
    affected_segment: str          # 事件原始的 affected_segment
    traffic_segment: str           # 用於車流分級與 ETE 的 RD_ 路段（可能來自 affected_road）
    station: str                   # BS_ 站點（人流事件才有）
    severity: str
    status: str
    event_type: str
    traffic_segment_source: str    # affected_segment | affected_road | none

    @property
    def is_road(self) -> bool:
        return self.kind == ROAD_INCIDENT

    @property
    def is_crowd(self) -> bool:
        return self.kind == CROWD_INCIDENT

    @property
    def is_signal_failure(self) -> bool:
        return self.kind == SIGNAL_FAILURE

    @property
    def requires_route_planning(self) -> bool:
        """只有 RD_ 路段的車禍/路障需要替代路徑重規劃（SOP 第 2 條）。"""
        return self.is_road


def _looks_like_signal_failure(incident: dict) -> bool:
    if (incident.get("type") or "") == SIGNAL_FAILURE_TYPE:
        return True
    description = incident.get("description") or ""
    return any(keyword in description for keyword in SIGNAL_FAILURE_KEYWORDS)


def classify_incident(incident: dict | None) -> IncidentClass:
    """
    判定事件類型，並解析出「用於車流評估的 RD_ 路段」。

    人流事件（BS_）若帶有 affected_road，就用那條 RD_ 路段做交通分級與 ETE。
    live_incidents.json 的人群推擠事件正是這樣描述的（BS_MRT_BL17 + RD_TPE_001），
    這也是命題所說的「人流 ↔ 車流融合」。
    """
    incident = incident if isinstance(incident, dict) else {}
    affected_segment = (incident.get("affected_segment") or "").strip()
    affected_road = (incident.get("affected_road") or "").strip()
    event_type = (incident.get("type") or "").strip()

    station = affected_segment if affected_segment.startswith(STATION_PREFIX) else ""

    # 車流評估路段：優先用 affected_segment（若本身是 RD_），否則採 affected_road。
    if affected_segment.startswith(SOP2_ROAD_PREFIX):
        traffic_segment, traffic_source = affected_segment, "affected_segment"
    elif affected_road.startswith(SOP2_ROAD_PREFIX):
        traffic_segment, traffic_source = affected_road, "affected_road"
    else:
        traffic_segment, traffic_source = "", "none"

    if _looks_like_signal_failure(incident):
        kind = SIGNAL_FAILURE
    elif station:
        kind = CROWD_INCIDENT
    elif affected_segment.startswith(SOP2_ROAD_PREFIX):
        kind = ROAD_INCIDENT
    else:
        kind = UNKNOWN_INCIDENT

    return IncidentClass(
        kind=kind,
        affected_segment=affected_segment,
        traffic_segment=traffic_segment,
        station=station,
        severity=(incident.get("severity") or "").strip(),
        status=(incident.get("status") or "").strip(),
        event_type=event_type,
        traffic_segment_source=traffic_source,
    )


# ---------------------------------------------------------------------------
# SOP 第 2 條 (a)(3) — 相交路口的上下游判定
# ---------------------------------------------------------------------------

# flow_direction 描述 → 下游方位。命題說 intersections 已依「上游→下游」排序，
# 這裡用來確認事故點落在哪個相交路口的哪一側。
_DOWNSTREAM_HINTS: tuple[tuple[str, str], ...] = (
    ("南下", "南"),
    ("往南", "南"),
    ("南向", "南"),
    ("北上", "北"),
    ("往北", "北"),
    ("北向", "北"),
    ("東行", "東"),
    ("往東", "東"),
    ("東向", "東"),
    ("西行", "西"),
    ("往西", "西"),
    ("西向", "西"),
)

_SIDE_TOKENS: tuple[tuple[str, str], ...] = (
    ("南側", "南"), ("以南", "南"), ("南端", "南"),
    ("北側", "北"), ("以北", "北"), ("北端", "北"),
    ("東側", "東"), ("以東", "東"), ("東端", "東"),
    ("西側", "西"), ("以西", "西"), ("西端", "西"),
)

_METHOD_LOCATED = "事故點定位"
_METHOD_MIDPOINT = "上游半段啟發式"


@dataclass(frozen=True, slots=True)
class UpstreamResolution:
    """上游判定結果，連同判定方法一起回傳，便於在報告中說明依據。"""

    upstream_indices: frozenset[int]
    method: str
    matched_intersection: str = ""
    incident_side: str = ""
    downstream_side: str = ""
    detail: str = ""

    def is_upstream(self, index: int) -> bool:
        return index in self.upstream_indices


# 「東西向」「南北向」只描述軸線，不是行進方向。先移除，否則「東西向」會被
# 誤判成「西向」。真正的方向資訊寫在括號裡，例如「南北向 (事故影響南下車流)」。
_AXIS_ONLY_TOKENS: tuple[str, ...] = ("東西向", "南北向")


def _downstream_side(flow_direction: str) -> str:
    text = flow_direction or ""
    for token in _AXIS_ONLY_TOKENS:
        text = text.replace(token, "")
    for hint, side in _DOWNSTREAM_HINTS:
        if hint in text:
            return side
    return ""


def _incident_side(location: str) -> str:
    text = location or ""
    for token, side in _SIDE_TOKENS:
        if token in text:
            return side
    return ""


def _match_intersection(intersections: list[str], location: str) -> tuple[int, str, int]:
    """
    在事故位置描述中找出被提及的相交路段。

    intersections 用路段全名（如「忠孝東路四段」），而事故描述通常寫「忠孝東路口」，
    所以由長到短嘗試前綴比對，取命中長度最長者。
    回傳 (索引, 命中的前綴, 命中長度)；找不到回傳 (-1, "", 0)。
    """
    text = location or ""
    best = (-1, "", 0)
    if not text:
        return best
    for index, name in enumerate(intersections):
        clean = (name or "").strip()
        for size in range(len(clean), 2, -1):
            prefix = clean[:size]
            if prefix and prefix in text:
                if size > best[2]:
                    best = (index, prefix, size)
                break
    return best


def resolve_upstream(
    intersections: list[str],
    flow_direction: str = "",
    location: str = "",
) -> UpstreamResolution:
    """
    判定 intersections 中哪些相交路口位於事故點上游。

    命題資料保證 intersections 已按車流「上游 → 下游」排序，所以問題化簡為
    「事故點落在陣列的哪個位置」。做法：
      1. 從事故位置描述找出被提及的相交路段（如「忠孝東路口」→ 忠孝東路四段）
      2. 由 flow_direction 得出下游方位（如「南下」→ 下游在南）
      3. 事故點若在該路口的下游側，該路口本身即為上游，取索引 <= 命中索引
         事故點若在上游側，取索引 < 命中索引
      4. 描述無法定位時，退回「陣列前半視為上游」的啟發式，並在報告標明方法
    """
    names = [str(n) for n in (intersections or [])]
    total = len(names)
    if total == 0:
        return UpstreamResolution(
            frozenset(), _METHOD_MIDPOINT, detail="該路段無相交路段資料"
        )

    index, matched, _ = _match_intersection(names, location)
    if index >= 0:
        downstream = _downstream_side(flow_direction)
        side = _incident_side(location)
        if side and downstream and side == downstream:
            bound = index + 1  # 事故點在該路口下游 → 該路口屬上游
            relation = f"事故點位於{matched}口{side}側，車流{downstream}向為下游"
        elif side and downstream and side != downstream:
            bound = index      # 事故點在該路口上游 → 該路口屬下游
            relation = f"事故點位於{matched}口{side}側，尚未到達該路口"
        else:
            bound = index      # 方位不明時保守處理，不把事故所在路口算成上游
            relation = f"事故點鄰近{matched}口，方位未明採保守判定"
        return UpstreamResolution(
            upstream_indices=frozenset(range(bound)),
            method=_METHOD_LOCATED,
            matched_intersection=names[index],
            incident_side=side,
            downstream_side=downstream,
            detail=relation,
        )

    midpoint = total / 2
    return UpstreamResolution(
        upstream_indices=frozenset(i for i in range(total) if i < midpoint),
        method=_METHOD_MIDPOINT,
        downstream_side=_downstream_side(flow_direction),
        detail="事故位置描述未指明相交路口，依 intersections 上游→下游排序取前半段",
    )


__all__ = [
    "LEVEL_A_THRESHOLD",
    "LEVEL_B_THRESHOLD",
    "SOP1_TRIGGER_SEGMENTS",
    "GREEN_LIGHT_EXTENSION_PCT",
    "SOP2_STATUSES",
    "SOP2_SEVERITIES",
    "SOP2_MIN_CAPACITY_VPH",
    "SOP2_ROAD_PREFIX",
    "SOP3_STATION",
    "SOP3_RELIEF_STATION",
    "SOP3_GROWTH_THRESHOLD",
    "SOP3_USER_COUNT_THRESHOLD",
    "SOP4_STATION",
    "SOP4_PEAK_THRESHOLD",
    "SOP4_DECLINE_THRESHOLD",
    "SIGNAL_FAILURE_TYPE",
    "SIGNAL_FAILURE_KEYWORDS",
    "SOP5_POLICE_PER_INTERSECTION",
    "SOP6_ROAMING_THRESHOLD",
    "SOP6_LANGUAGES",
    "SOP6_DEFAULT_LANGUAGES",
    "ETE_BASE_CLEARANCE",
    "ETE_SATURATION_BASELINE",
    "ETE_SATURATION_FACTOR",
    "ETE_FORMULA",
    "TIME_FMT",
    "ROAD_INCIDENT",
    "CROWD_INCIDENT",
    "SIGNAL_FAILURE",
    "UNKNOWN_INCIDENT",
    "IncidentClass",
    "UpstreamResolution",
    "assess_congestion_level",
    "classify_incident",
    "is_trigger_segment",
    "level_description",
    "police_required",
    "resolve_upstream",
    "thresholds_payload",
]
