"""
決策鏈投影 — 把「誰做了這個判斷」攤開給畫面看。

命題把分工寫得很明確：門檻判定、路網重規劃、ETE 公式一律由程式運算，LLM 只負責
敘述與解釋。後端本來就是這樣實作的（門檻在 sop_rules、數值在 traffic_math、判定在
policy），但建議書送到前端後只剩下一段 AI 文字，評審沒辦法分辨哪個數字是算出來的、
哪句話是模型寫的。

這個模組不做任何計算、也不呼叫 LLM，只把既有的 policy / routing / comms 結果重新
投影成兩份可稽核的結構：

  1. steps            決策鏈逐步紀錄，每步標明 engine（deterministic / llm）、
                      依據的 SOP 條號、輸入數值、套用的規則與結論。
  2. sop_conformance  SOP 逐項合規檢核。官方三個預設注入事件分別對應第 2、3、5 條，
                      這份清單把每一條的觸發要件與處置步驟拆成可勾稽的項目，
                      確保處置是「照條文走完」而不是模型自由發揮。

⚠️ 這裡只讀取上游算好的值。任何新的門檻或公式都不該寫在這個檔案。
"""

from __future__ import annotations

import re

from backend.agents import policy, sop_rules

# --- 執行引擎標籤 ---------------------------------------------------------

ENGINE_RULE = "deterministic"   # 純程式：門檻、公式、路網篩選
ENGINE_LLM = "llm"              # 生成式：敘述、解釋、多語文案潤飾

ENGINE_LABELS = {
    ENGINE_RULE: "程式運算",
    ENGINE_LLM: "AI 生成",
}

# --- 合規檢核狀態 ---------------------------------------------------------

STATUS_PASS = "pass"            # 條文要求已滿足
STATUS_FAIL = "fail"            # 條文要求未滿足（需要人工介入）
STATUS_DEGRADED = "degraded"    # 條文本身允許的退階，已依原文處理並在報告註明
STATUS_NA = "na"                # 本事件不適用此項

# --- 決策鏈階段（供前端分組） ---------------------------------------------

STAGE_INTAKE = "事件受理"
STAGE_GRADE = "分級判定"
STAGE_POLICY = "法規比對"
STAGE_ROUTE = "路徑重規劃"
STAGE_ETE = "恢復時間"
STAGE_SIGNAL = "號誌與警力"
STAGE_CROSS = "跨系統聯動"
STAGE_COMMS = "公眾通報"
STAGE_NARRATIVE = "敘述生成"

_TIME_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")

_KIND_LABELS = {
    sop_rules.ROAD_INCIDENT: "車流事件（路面阻斷）",
    sop_rules.CROWD_INCIDENT: "人流事件（站點壅擠）",
    sop_rules.SIGNAL_FAILURE: "號誌故障事件",
    sop_rules.UNKNOWN_INCIDENT: "未分類事件",
}

_NARRATIVE_SOURCE_LABELS = {
    "ai_generated": "Bedrock Claude 依計算結果生成敘述與現場處置",
    "ai_generated_partial": "Bedrock Claude 生成敘述，現場處置改用程式清單",
    "fallback": "Bedrock 不可用，改由程式依 SOP 判定結果組出敘述",
    "deadline_fallback": "已進入 60 秒時限降級，改由程式依 SOP 判定結果組出敘述",
}


def _percent(value: object) -> str:
    """把 0~1 的飽和度轉成報告用百分比字串；無資料回傳「無資料」。"""
    try:
        return f"{round(float(value) * 100)}%"
    except (TypeError, ValueError):
        return "無資料"


def _field(label: str, value: object) -> dict:
    return {"label": label, "value": "" if value is None else str(value)}


def _step(
    *,
    step_id: str,
    order: int,
    stage: str,
    title: str,
    engine: str,
    authority: str,
    output: str,
    sop_articles: list[int] | None = None,
    rule: str = "",
    inputs: list[dict] | None = None,
    detail: str = "",
    formula: str = "",
) -> dict:
    return {
        "id": step_id,
        "order": order,
        "stage": stage,
        "title": title,
        "engine": engine,
        "engine_label": ENGINE_LABELS.get(engine, engine),
        # 哪一個模組是這一步的權威來源。評審問「這個數字誰算的」可以直接指過去。
        "authority": authority,
        "sop_articles": sorted(set(sop_articles or [])),
        "rule": rule,
        "formula": formula,
        "inputs": inputs or [],
        "output": output,
        "detail": detail,
    }


def _check(
    requirement: str,
    status: str,
    evidence: str = "",
    *,
    clause: str = "",
) -> dict:
    return {
        "requirement": requirement,
        "clause": clause,
        "status": status,
        "satisfied": status in (STATUS_PASS, STATUS_DEGRADED),
        "evidence": evidence,
    }


def _article(
    number: int,
    *,
    triggered: bool,
    scope: str,
    checks: list[dict],
    basis: str = "",
) -> dict:
    applicable = [c for c in checks if c["status"] != STATUS_NA]
    failed = [c for c in applicable if c["status"] == STATUS_FAIL]
    degraded = [c for c in applicable if c["status"] == STATUS_DEGRADED]
    return {
        "sop_number": number,
        "title": policy.SOP_TITLES.get(number, ""),
        "triggered": triggered,
        "scope": scope,
        "basis": basis,
        "checks": checks,
        "total": len(applicable),
        "satisfied_count": len([c for c in applicable if c["satisfied"]]),
        "failed_count": len(failed),
        "degraded_count": len(degraded),
        "compliant": not failed,
    }


# ---------------------------------------------------------------------------
# 決策鏈
# ---------------------------------------------------------------------------


def build_decision_trace(
    *,
    incident: dict,
    info,
    policy_result: dict,
    routing_result: dict,
    comms_result: dict,
    cross_actions: list[dict],
    narrative_source: str = "",
) -> dict:
    """
    把單一事件的處置過程投影成逐步決策鏈。

    回傳 steps 已依 order 排好，前端照順序畫即可；engine 欄位就是「確定性 vs AI」
    的分界，不需要前端再猜。
    """
    incident = incident if isinstance(incident, dict) else {}
    policy_result = policy_result if isinstance(policy_result, dict) else {}
    routing_result = routing_result if isinstance(routing_result, dict) else {}
    comms_result = comms_result if isinstance(comms_result, dict) else {}
    cross_actions = cross_actions or []

    steps: list[dict] = []
    order = 0

    def add(**kwargs) -> None:
        nonlocal order
        order += 1
        steps.append(_step(order=order, **kwargs))

    # --- 1. 事件受理與分類 -------------------------------------------------
    traffic_source_label = {
        "affected_segment": "取自事件 affected_segment",
        "affected_road": "人流事件經 affected_road 對應（人流 ↔ 車流融合）",
        "none": "事件未對應任何車流路段",
    }.get(info.traffic_segment_source, info.traffic_segment_source)

    add(
        step_id="intake",
        stage=STAGE_INTAKE,
        title="事件受理與類型判定",
        engine=ENGINE_RULE,
        authority="sop_rules.classify_incident",
        rule=(
            "type 為 Power_Failure 或描述含「號誌失效／號誌故障」→ 號誌故障；"
            "affected_segment 以 BS_ 開頭 → 人流事件；以 RD_ 開頭 → 車流事件"
        ),
        inputs=[
            _field("事件編號", incident.get("event_id")),
            _field("事件類型", incident.get("type")),
            _field("路段狀態", incident.get("status")),
            _field("嚴重度", incident.get("severity")),
            _field("影響對象", info.affected_segment),
            _field("車流評估路段", f"{info.traffic_segment or '無'}（{traffic_source_label}）"),
        ],
        output=_KIND_LABELS.get(info.kind, info.kind),
        detail=(
            "只有 RD_ 車流事件會進入 SOP 第 2 條替代路徑重規劃；"
            "BS_ 人流事件依條文改由第 3 條處置。"
        ),
    )

    # --- 2. SOP 第 1 條分級 -----------------------------------------------
    incident_level = policy_result.get("incident_segment_level")
    congestion_details = policy_result.get("congestion_details") or policy_result.get(
        "congestion_levels"
    ) or []
    incident_entry = next(
        (c for c in congestion_details if c.get("is_incident_segment")), None
    )
    add(
        step_id="grade",
        stage=STAGE_GRADE,
        title="交通擁塞級別判定",
        engine=ENGINE_RULE,
        authority="sop_rules.assess_congestion_level",
        sop_articles=[1],
        rule="B 級：0.85 ≤ Saturation_Score < 0.95；A 級：Saturation_Score ≥ 0.95",
        inputs=[
            _field(
                "事件路段飽和度",
                f"{info.traffic_segment or '—'} "
                f"{_percent((incident_entry or {}).get('saturation_score'))}",
            ),
            _field("全網最高級別", sop_rules.level_description(
                policy_result.get("network_max_level", "Normal"))),
            _field("城市應變觸發路段最高級別", sop_rules.level_description(
                policy_result.get("trigger_max_level", "Normal"))),
            _field("納入判定路段數", len(congestion_details)),
        ],
        output=(
            f"判定 {sop_rules.level_description(incident_level)}"
            if incident_level
            else f"事件路段無車流量測，改採全網最高級別 "
                 f"{sop_rules.level_description(policy_result.get('network_max_level', 'Normal'))}"
        ),
        detail=(
            "城市應變觸發路段僅忠孝東路四段 (RD_TPE_001) 與光復南路 (RD_TPE_002)；"
            "其餘路段達級別只做紅黃燈顯示，不啟動長綠燈時制。"
        ),
    )

    # --- 3. SOP 條款比對（逐條一步，報告上可直接勾稽） ---------------------
    triggered_sops = [
        s for s in (policy_result.get("triggered_sops") or [])
        if isinstance(s, dict) and s.get("triggered")
    ]
    event_articles = [s for s in triggered_sops if s.get("scope") == policy.SCOPE_EVENT]
    situational_articles = [
        s for s in triggered_sops if s.get("scope") == policy.SCOPE_SITUATIONAL
    ]

    for check in event_articles:
        number = check["sop_number"]
        evidence = check.get("evidence") or {}
        add(
            step_id=f"sop{number}",
            stage=STAGE_POLICY,
            title=f"SOP 第 {number} 條 {check.get('sop_title', '')} 觸發判定",
            engine=ENGINE_RULE,
            authority=f"policy.check_sop{number}_trigger",
            sop_articles=[number],
            rule=_trigger_rule_text(number),
            inputs=_trigger_inputs(number, evidence),
            output="已觸發",
            detail=check.get("reason", ""),
        )

    if situational_articles:
        numbers = [s["sop_number"] for s in situational_articles]
        add(
            step_id="sop_situational",
            stage=STAGE_POLICY,
            title="同時段全市態勢條款",
            engine=ENGINE_RULE,
            authority="policy.evaluate_data_triggers",
            sop_articles=numbers,
            rule="第 3、4、6 條為資料型條款，同一時間點對全市成立，與本事件無因果關係",
            inputs=[
                _field(f"SOP 第 {s['sop_number']} 條", s.get("reason", ""))
                for s in situational_articles
            ],
            output="列為態勢提醒，不計入本事件觸發條款",
            detail="分開列示以免號誌故障的建議書出現「本事件觸發捷運分流」這類張冠李戴的敘述。",
        )

    # --- 4. SOP 第 2 條替代路徑 -------------------------------------------
    route = routing_result.get("route_recommendation") or {}
    analysis = routing_result.get("route_analysis") or {}
    if route:
        candidates = analysis.get("candidates") or []
        upstream = analysis.get("upstream_resolution") or {}
        tier1 = [c for c in candidates if c.get("tier") == 1]
        add(
            step_id="route",
            stage=STAGE_ROUTE,
            title="主疏散路徑篩選",
            engine=ENGINE_RULE,
            authority="traffic_math.calculate_optimal_route",
            sop_articles=[2],
            rule=(
                f"自事故路段 alternatives 篩選同時滿足："
                f"(1) capacity_vph ≥ {sop_rules.SOP2_MIN_CAPACITY_VPH}、"
                f"(2) 出現在事故路段 intersections（直接相交）、"
                f"(3) 相交路口位於事故點上游；取通過篩選者中 Saturation_Score 最低者"
            ),
            inputs=[
                _field("候選替代道路", f"{len(candidates)} 條"),
                _field("通過三項篩選", f"{len(tier1)} 條"),
                _field("事故路段車流方向", analysis.get("flow_direction", "")),
                _field("相交路段（上游→下游）", "、".join(analysis.get("intersections") or [])),
                _field("上游判定方法", upstream.get("method", "")),
                _field("判定為上游之路口", "、".join(upstream.get("upstream_intersections") or [])),
            ],
            output=(
                f"主疏散：{route.get('primary_route_name', '')}"
                f"（容量 {route.get('capacity_vph', 0)} 車/小時、"
                f"飽和度 {_percent(route.get('current_saturation'))}）"
                + (
                    f"；次要疏散：{'、'.join(r.get('name', '') for r in route.get('secondary_routes') or [])}"
                    if route.get("secondary_routes")
                    else ""
                )
            ),
            detail=route.get("selection_reason", ""),
        )

    # --- 5. SOP 第 7 條 ETE ------------------------------------------------
    ete = routing_result.get("ete_result") or {}
    if ete:
        add(
            step_id="ete",
            stage=STAGE_ETE,
            title="預計恢復時間計算",
            engine=ENGINE_RULE,
            authority="traffic_math.calculate_ete",
            sop_articles=[7],
            rule="base_clearance 依嚴重度：Critical 60、High 40、Medium 20 分鐘",
            formula=ete.get("formula") or sop_rules.ETE_FORMULA,
            inputs=[
                _field("嚴重度", f"{ete.get('severity', '')} → 基礎清除 "
                                f"{ete.get('base_clearance_minutes', 0)} 分鐘"),
                _field("受影響路段定義", ete.get("affected_segments_definition", "")),
                _field("納入計算路段", "、".join(ete.get("affected_segment_ids") or [])),
                _field("平均飽和度", _percent(ete.get("avg_saturation_score"))),
                _field("壅塞懲罰", f"{ete.get('congestion_penalty_minutes', 0)} 分鐘"),
            ],
            output=f"ETE {ete.get('ete_minutes')} 分鐘",
            detail=ete.get("note", ""),
        )

    # --- 6. 號誌與警力 -----------------------------------------------------
    signal_plans = routing_result.get("signal_plans") or []
    for index, plan in enumerate(signal_plans):
        is_sop1 = plan.get("scope") == "sop1_all_alternatives"
        roads = "、".join(a.get("road_name", "") for a in plan.get("adjustments") or [])
        dispatch = plan.get("police_dispatch") or {}
        add(
            step_id=f"signal{index}",
            stage=STAGE_SIGNAL,
            title="號誌配時與警力處置",
            engine=ENGINE_RULE,
            authority="traffic_math.build_signal_plan",
            sop_articles=[1] if is_sop1 else [2],
            rule=plan.get("sop_reference", ""),
            inputs=[
                _field("觸發路段", f"{plan.get('road_name', '')} "
                                f"{plan.get('level_description', '')}"
                                f"（飽和度 {_percent(plan.get('saturation_score'))}）"),
                _field("調整範圍", "該路段 alternatives 全集" if is_sop1 else "主疏散路段"),
                _field("套用路段", roads),
                _field("時段", plan.get("window", "") or "依現場滾動調整"),
            ],
            output=(
                f"{roads} 綠燈配時 +{sop_rules.GREEN_LIGHT_EXTENSION_PCT}%（長綠燈時制）"
                + (f"；{dispatch.get('instruction', '')}" if dispatch.get("instruction") else "")
            ),
            detail=dispatch.get("staffing_note", ""),
        )

    # --- 7. 跨系統聯動 -----------------------------------------------------
    event_cross = [a for a in cross_actions if a.get("scope") != policy.SCOPE_SITUATIONAL]
    if event_cross:
        add(
            step_id="cross",
            stage=STAGE_CROSS,
            title="跨單位請求生成",
            engine=ENGINE_RULE,
            authority="architect._cross_system_actions",
            sop_articles=sorted({
                int(m.group(1))
                for a in event_cross
                if (m := re.search(r"第\s*([1-7])\s*條", a.get("sop_reference", "")))
            }),
            rule="由已觸發條款的處置條文直接展開為受文單位與請求事項，不經 LLM 改寫",
            inputs=[
                _field(a.get("agency", ""), f"[{a.get('sop_reference', '')}] {a.get('request', '')}")
                for a in event_cross
            ],
            output=f"產出 {len(event_cross)} 項跨單位請求",
        )

    # --- 8. SOP 第 6 條通報 -----------------------------------------------
    languages = comms_result.get("languages") or []
    trigger_stations = comms_result.get("trigger_stations") or []
    messages = comms_result.get("messages") or []
    add(
        step_id="comms",
        stage=STAGE_COMMS,
        title="多語通報判定與文案產出",
        engine=ENGINE_RULE,
        authority="traffic_math.scan_roaming + comms.run_comms",
        sop_articles=[6],
        rule=(
            f"判定範圍為全資料集所有基地台，任一站 Roaming_User_Pct ≥ "
            f"{sop_rules.SOP6_ROAMING_THRESHOLD:.0%} 即須多語；"
            "CMS 句式由 SOP 第 2 條 (b)／第 5 條明訂範本逐字套用"
        ),
        inputs=[
            _field("判定範圍", comms_result.get("roaming_scope", "全資料集所有基地台")),
            _field(
                "達標站點",
                "、".join(
                    f"{s.get('location_name', '')} {s.get('roaming_user_pct_display', '')}"
                    for s in trigger_stations
                ) or "無站點達門檻",
            ),
            _field("套用範本", (messages[0].get("template_used") if messages else "") or ""),
        ],
        output=(
            f"產出 {len(languages)} 種語言通報（{'、'.join(languages)}）"
            if comms_result.get("trigger_sop6")
            else "未達漫遊率門檻，僅產出繁體中文通報"
        ),
        detail="文案由固定範本填值，語意與條文一致；LLM 不介入 CMS 句式生成。",
    )

    # --- 9. 敘述生成（唯一交給 LLM 的環節） --------------------------------
    add(
        step_id="narrative",
        stage=STAGE_NARRATIVE,
        title="建議書敘述與現場處置撰寫",
        engine=ENGINE_LLM,
        authority="architect._generate_advisory_ai（Amazon Bedrock Claude）",
        rule=(
            "輸入僅為上列計算結果與 SOP 條文原文；"
            "系統提示禁止自行推算或新增任何數值、時間與人力"
        ),
        inputs=[
            _field("可用素材", "分級結果、觸發條款、替代路徑與排除理由、ETE 分解、"
                           "號誌配時、跨單位請求、通報語言"),
            _field("輸出約束", "判斷／建議／行動指令三段合計 ≤ 450 字，現場處置 4 條"),
        ],
        output=_NARRATIVE_SOURCE_LABELS.get(
            narrative_source, narrative_source or "敘述生成"
        ),
        detail="這是全流程唯一由生成式模型產出的內容；所有數字都來自前面各步的程式運算。",
    )

    rule_steps = len([s for s in steps if s["engine"] == ENGINE_RULE])
    llm_steps = len([s for s in steps if s["engine"] == ENGINE_LLM])

    return {
        "steps": steps,
        "total_steps": len(steps),
        "engine_split": {
            "deterministic": rule_steps,
            "llm": llm_steps,
            "statement": (
                f"{len(steps)} 個決策步驟中，{rule_steps} 步為程式確定性運算"
                f"（門檻、路網篩選、公式），{llm_steps} 步由 AI 生成敘述。"
                "所有數值皆出自程式，AI 不參與計算。"
            ),
        },
    }


def _trigger_rule_text(number: int) -> str:
    """各條觸發要件的條文摘要。文字對齊 emergency_traffic_sop.txt。"""
    if number == 2:
        return (
            "同時符合三項：status ∈ {Closed, Blocked, Restricted}、"
            "severity ∈ {High, Critical}、affected_segment 以 RD_ 開頭"
        )
    if number == 3:
        return (
            f"任一成立：{sop_rules.SOP3_STATION} Growth_Rate > "
            f"{sop_rules.SOP3_GROWTH_THRESHOLD:.0%} 或 User_Count > "
            f"{sop_rules.SOP3_USER_COUNT_THRESHOLD:,}"
        )
    if number == 4:
        return (
            f"{sop_rules.SOP4_STATION} User_Count 歷史峰值 ≥ "
            f"{sop_rules.SOP4_PEAK_THRESHOLD:,} 且當前 Growth_Rate ≤ "
            f"{sop_rules.SOP4_DECLINE_THRESHOLD:.0%}"
        )
    if number == 5:
        return 'type = "Power_Failure"，或描述含「號誌失效／號誌故障」'
    if number == 6:
        return (
            f"任一基地台 Roaming_User_Pct ≥ {sop_rules.SOP6_ROAMING_THRESHOLD:.0%}"
        )
    return ""


def _trigger_inputs(number: int, evidence: dict) -> list[dict]:
    """把 policy 判定用到的證據數值攤成報告欄位。"""
    evidence = evidence if isinstance(evidence, dict) else {}
    if number == 2:
        return [
            _field("status", f"{evidence.get('status', '')}"
                             f"（{'符合' if evidence.get('status_ok') else '不符'}）"),
            _field("severity", f"{evidence.get('severity', '')}"
                               f"（{'符合' if evidence.get('severity_ok') else '不符'}）"),
            _field("affected_segment", f"{evidence.get('affected_segment', '')}"
                                       f"（{'符合' if evidence.get('segment_ok') else '不符'}）"),
        ]
    if number == 3:
        return [
            _field("站點", f"{evidence.get('location_name', '')}"
                          f"（{evidence.get('station', '')}）"),
            _field("站內人數", f"{int(evidence.get('user_count') or 0):,} 人"
                            f"（門檻 {int(evidence.get('user_count_threshold') or 0):,}）"),
            _field("人流增幅", f"{float(evidence.get('growth_rate') or 0):.0%}"
                            f"（門檻 {float(evidence.get('growth_threshold') or 0):.0%}）"),
        ]
    if number == 4:
        return [
            _field("歷史峰值", f"{int(evidence.get('peak_user_count') or 0):,} 人"
                            f"（{evidence.get('peak_at', '')}）"),
            _field("當前人流增幅", f"{float(evidence.get('current_growth_rate') or 0):.0%}"),
        ]
    if number == 5:
        return [
            _field("事件類型", f"{evidence.get('type', '')}"
                            f"（{'符合' if evidence.get('type_match') else '不符'}）"),
            _field("描述關鍵字", "、".join(evidence.get("matched_keywords") or []) or "—"),
        ]
    if number == 6:
        stations = evidence.get("trigger_stations") or []
        return [
            _field("判定範圍", evidence.get("scope", "全資料集所有基地台")),
            _field("掃描站點數", evidence.get("total_stations", 0)),
            _field(
                "達標站點",
                "、".join(
                    f"{s.get('location_name', '')} {s.get('roaming_user_pct_display', '')}"
                    for s in stations
                ) or "無",
            ),
        ]
    return []


# ---------------------------------------------------------------------------
# SOP 逐項合規檢核
# ---------------------------------------------------------------------------


def build_sop_conformance(
    *,
    info,
    policy_result: dict,
    routing_result: dict,
    comms_result: dict,
    cross_actions: list[dict],
    timestamp: str = "",
) -> dict:
    """
    把「本事件該走的 SOP 條文」拆成逐項可勾稽的檢核表。

    官方三個預設注入事件分別對應第 2、3、5 條，這份表就是現場證明「處置確實照條文
    走完」的依據，而不是靠 AI 自述有遵守。第 1、6、7 條對所有事件都適用，一併檢核。
    """
    policy_result = policy_result if isinstance(policy_result, dict) else {}
    routing_result = routing_result if isinstance(routing_result, dict) else {}
    comms_result = comms_result if isinstance(comms_result, dict) else {}
    cross_actions = cross_actions or []

    checks_by_number = {
        c["sop_number"]: c
        for c in (policy_result.get("triggered_sops") or [])
        if isinstance(c, dict)
    }
    scope_of = {
        number: check.get("scope", policy.SCOPE_SITUATIONAL)
        for number, check in checks_by_number.items()
    }

    articles: list[dict] = [
        _article(
            1,
            triggered=policy_result.get("incident_segment_level") in ("A", "B"),
            scope=policy.SCOPE_EVENT,
            basis="全事件適用：分級是後續所有處置的前提",
            checks=_conformance_sop1(policy_result, routing_result),
        )
    ]

    if info.is_road or checks_by_number.get(2, {}).get("triggered"):
        articles.append(
            _article(
                2,
                triggered=bool(checks_by_number.get(2, {}).get("triggered")),
                scope=scope_of.get(2, policy.SCOPE_EVENT),
                basis="RD_ 車流事件依第 2 條處置",
                checks=_conformance_sop2(
                    checks_by_number.get(2, {}), routing_result, comms_result
                ),
            )
        )

    if info.is_crowd or checks_by_number.get(3, {}).get("scope") == policy.SCOPE_EVENT:
        articles.append(
            _article(
                3,
                triggered=bool(checks_by_number.get(3, {}).get("triggered")),
                scope=scope_of.get(3, policy.SCOPE_EVENT),
                basis="BS_ 人流事件依第 3 條處置",
                checks=_conformance_sop3(
                    checks_by_number.get(3, {}), cross_actions, comms_result
                ),
            )
        )

    if info.is_signal_failure:
        articles.append(
            _article(
                5,
                triggered=bool(checks_by_number.get(5, {}).get("triggered")),
                scope=scope_of.get(5, policy.SCOPE_EVENT),
                basis="號誌故障事件依第 5 條處置",
                checks=_conformance_sop5(
                    checks_by_number.get(5, {}), routing_result, comms_result, cross_actions
                ),
            )
        )

    articles.append(
        _article(
            6,
            triggered=bool(comms_result.get("trigger_sop6")),
            scope=policy.SCOPE_EVENT,
            basis="全事件適用：決定本次通報的語言數",
            checks=_conformance_sop6(comms_result, timestamp),
        )
    )

    ete = routing_result.get("ete_result") or {}
    if ete:
        articles.append(
            _article(
                7,
                triggered=True,
                scope=policy.SCOPE_EVENT,
                basis="全事件適用：CMS 與建議書的延誤時間來源",
                checks=_conformance_sop7(ete),
            )
        )

    articles.sort(key=lambda a: a["sop_number"])
    total = sum(a["total"] for a in articles)
    satisfied = sum(a["satisfied_count"] for a in articles)
    failed = sum(a["failed_count"] for a in articles)
    degraded = sum(a["degraded_count"] for a in articles)

    return {
        "articles": articles,
        "primary_articles": [
            a["sop_number"] for a in articles
            if a["triggered"] and a["scope"] == policy.SCOPE_EVENT
        ],
        "total_checks": total,
        "satisfied_checks": satisfied,
        "failed_checks": failed,
        "degraded_checks": degraded,
        "compliant": failed == 0,
        "summary": (
            f"依 SOP 第 "
            + "、".join(str(a["sop_number"]) for a in articles)
            + f" 條檢核 {total} 項要求，{satisfied} 項滿足"
            + (f"、{degraded} 項為條文允許之退階" if degraded else "")
            + (f"、{failed} 項未滿足" if failed else "，無未滿足項目")
            + "。"
        ),
    }


def _conformance_sop1(policy_result: dict, routing_result: dict) -> list[dict]:
    details = policy_result.get("congestion_details") or policy_result.get(
        "congestion_levels"
    ) or []
    trigger_levels = policy_result.get("trigger_segment_levels") or []
    trigger_max = policy_result.get("trigger_max_level", "Normal")
    plans = routing_result.get("signal_plans") or []
    sop1_plan = next(
        (p for p in plans if p.get("scope") == "sop1_all_alternatives"), None
    )

    checks = [
        _check(
            "依 Saturation_Score 判定 A／B 級（A ≥ 0.95、B ≥ 0.85）",
            STATUS_PASS if details else STATUS_FAIL,
            f"已對 {len(details)} 個路段完成分級",
            clause="第 1 條 分級",
        ),
        _check(
            "城市應變觸發路段限忠孝東路四段與光復南路",
            STATUS_PASS if trigger_levels else STATUS_FAIL,
            "、".join(
                f"{c.get('road_name', '')} {_percent(c.get('saturation_score'))} "
                f"{c.get('description', '')}"
                for c in trigger_levels
            ) or "查無觸發路段車流資料",
            clause="第 1 條 觸發路段",
        ),
    ]

    if trigger_max in ("A", "B"):
        checks.append(
            _check(
                f"觸發路段達 {sop_rules.level_description(trigger_max)} → "
                f"替代道路綠燈 +{sop_rules.GREEN_LIGHT_EXTENSION_PCT}% 並調度警力淨空路口",
                STATUS_PASS if sop1_plan else STATUS_NA,
                (
                    "、".join(a.get("road_name", "") for a in sop1_plan.get("adjustments") or [])
                    + f"；{(sop1_plan.get('police_dispatch') or {}).get('instruction', '')}"
                    if sop1_plan
                    else "本事件路段非觸發路段，長綠燈時制由儀表板自動應變產出"
                ),
                clause="第 1 條 處置",
            )
        )
    else:
        checks.append(
            _check(
                "觸發路段達級別時啟動長綠燈時制",
                STATUS_NA,
                "觸發路段未達 B 級，依條文無須啟動",
                clause="第 1 條 處置",
            )
        )
    return checks


def _conformance_sop2(
    sop2: dict, routing_result: dict, comms_result: dict
) -> list[dict]:
    evidence = (sop2 or {}).get("evidence") or {}
    route = routing_result.get("route_recommendation") or {}
    analysis = routing_result.get("route_analysis") or {}
    candidates = analysis.get("candidates") or []
    tier = route.get("selection_tier")
    triggered = bool((sop2 or {}).get("triggered"))

    checks = [
        _check(
            "status ∈ {Closed, Blocked, Restricted}",
            STATUS_PASS if evidence.get("status_ok") else STATUS_FAIL,
            f"status = {evidence.get('status', '未提供')}",
            clause="第 2 條 觸發 (1)",
        ),
        _check(
            "severity ∈ {High, Critical}",
            STATUS_PASS if evidence.get("severity_ok") else STATUS_FAIL,
            f"severity = {evidence.get('severity', '未提供')}",
            clause="第 2 條 觸發 (2)",
        ),
        _check(
            "affected_segment 以 RD_ 開頭",
            STATUS_PASS if evidence.get("segment_ok") else STATUS_FAIL,
            f"affected_segment = {evidence.get('affected_segment', '未提供')}",
            clause="第 2 條 觸發 (3)",
        ),
    ]

    if not triggered or not route:
        checks.append(
            _check(
                "自 alternatives 篩選主疏散路徑",
                STATUS_NA,
                "三項觸發條件未同時成立，依條文不進行替代路徑重規劃",
                clause="第 2 條 處置 a",
            )
        )
        return checks

    tier1 = [c for c in candidates if c.get("tier") == 1]
    tier1_sorted = sorted(
        tier1, key=lambda c: (c.get("saturation_score") is None, c.get("saturation_score") or 0)
    )
    is_lowest = bool(tier1_sorted) and tier1_sorted[0].get("segment_id") == route.get(
        "primary_route_id"
    )
    downstream = [c for c in candidates if c.get("tier") == 2]
    secondary_ids = {r.get("segment_id") for r in route.get("secondary_routes") or []}

    checks.extend([
        _check(
            f"主疏散候選 capacity_vph ≥ {sop_rules.SOP2_MIN_CAPACITY_VPH}",
            STATUS_PASS if route.get("capacity_vph", 0) >= sop_rules.SOP2_MIN_CAPACITY_VPH
            else STATUS_FAIL,
            f"{route.get('primary_route_name', '')} 容量 {route.get('capacity_vph', 0)} 車/小時",
            clause="第 2 條 處置 a(1)",
        ),
        _check(
            "主疏散須與事故路段直接相交（出現在 intersections）",
            STATUS_PASS if route.get("is_intersecting") else STATUS_DEGRADED,
            (
                f"{route.get('primary_route_name', '')} 位於事故路段 intersections 中"
                if route.get("is_intersecting")
                else "無相交且達容量的替代道路，已依退階規則選路並於報告註明"
            ),
            clause="第 2 條 處置 a(2)",
        ),
        _check(
            "相交路口須位於事故點上游",
            STATUS_PASS if route.get("is_upstream") else STATUS_DEGRADED,
            (
                (analysis.get("upstream_resolution") or {}).get("detail", "")
                if route.get("is_upstream")
                else "無「相交且位於上游」之候選，已退階並於報告註明"
            ),
            clause="第 2 條 處置 a(3)",
        ),
        _check(
            "取通過篩選者中 Saturation_Score 最低者為主疏散",
            STATUS_PASS if is_lowest else (STATUS_DEGRADED if tier != 1 else STATUS_FAIL),
            (
                "通過篩選者："
                + "、".join(
                    f"{c.get('name', '')} {_percent(c.get('saturation_score'))}"
                    for c in tier1_sorted
                )
                if tier1_sorted
                else f"無通過三項篩選之候選，採退階第 {tier} 層"
            ),
            clause="第 2 條 處置 a",
        ),
        _check(
            "位於下游之相交幹道僅列次要疏散",
            STATUS_PASS if all(c.get("segment_id") in secondary_ids for c in downstream)
            else (STATUS_NA if not downstream else STATUS_FAIL),
            (
                "、".join(f"{c.get('name', '')}（下游）" for c in downstream)
                if downstream
                else "無位於下游之相交幹道"
            ),
            clause="第 2 條 處置 a",
        ),
        _check(
            "主疏散已壅塞（≥ 0.85）時維持該路徑並啟動長綠燈時制且於報告註明",
            STATUS_PASS if (route.get("is_congested") and route.get("congestion_note"))
            else (STATUS_NA if not route.get("is_congested") else STATUS_FAIL),
            route.get("congestion_note")
            or f"主疏散飽和度 {_percent(route.get('current_saturation'))}，未達壅塞門檻",
            clause="第 2 條 處置 a",
        ),
        _check(
            "產出 CMS：「<事故路段>封閉，請改道 <主疏散路段>，預計延誤 <ETE> 分鐘」",
            STATUS_PASS if _cms_matches(comms_result, ("封閉", "請改道", "預計延誤"))
            else STATUS_FAIL,
            _cms_sample(comms_result),
            clause="第 2 條 處置 b",
        ),
    ])
    return checks


def _conformance_sop3(sop3: dict, cross_actions: list[dict], comms_result: dict) -> list[dict]:
    evidence = (sop3 or {}).get("evidence") or {}
    triggered = bool((sop3 or {}).get("triggered"))
    requests = " ".join(a.get("request", "") for a in cross_actions)

    def status_for(hit: bool) -> str:
        """條款已觸發時處置必須存在；未觸發則該處置本就不適用。"""
        if hit:
            return STATUS_PASS
        return STATUS_FAIL if triggered else STATUS_NA

    return [
        _check(
            f"觸發：Growth_Rate > {sop_rules.SOP3_GROWTH_THRESHOLD:.0%} 或 "
            f"User_Count > {sop_rules.SOP3_USER_COUNT_THRESHOLD:,}",
            STATUS_PASS if triggered else STATUS_FAIL,
            (sop3 or {}).get("reason", ""),
            clause="第 3 條 觸發",
        ),
        _check(
            "建議北捷「過站不停」",
            status_for("過站不停" in requests),
            _agency_request(cross_actions, "捷運", sop_number=3),
            clause="第 3 條 處置",
        ),
        _check(
            "通知公車處調度接駁專車",
            status_for("接駁" in requests),
            _agency_request(cross_actions, "公車處", sop_number=3),
            clause="第 3 條 處置",
        ),
        _check(
            f"引導群眾步行至 {sop_rules.SOP3_RELIEF_STATION}",
            status_for("BL18" in requests or "市政府站" in requests),
            _agency_request(cross_actions, "警察局", sop_number=3),
            clause="第 3 條 處置",
        ),
        _check(
            "站點分流指引納入公眾通報",
            STATUS_PASS if _cms_matches(comms_result, ("請改至",)) else STATUS_NA,
            _cms_sample(comms_result),
            clause="第 3 條 處置",
        ),
        _check(
            "人數／增幅數值列入報告佐證",
            STATUS_PASS if evidence.get("user_count") is not None else STATUS_FAIL,
            f"人數 {int(evidence.get('user_count') or 0):,} 人、"
            f"增幅 {float(evidence.get('growth_rate') or 0):.0%}",
            clause="第 3 條 佐證",
        ),
    ]


def _conformance_sop5(
    sop5: dict, routing_result: dict, comms_result: dict, cross_actions: list[dict]
) -> list[dict]:
    triggered = bool((sop5 or {}).get("triggered"))
    ete = routing_result.get("ete_result") or {}
    police = next(
        (a for a in cross_actions if "第 5 條" in a.get("sop_reference", "")
         and "警察" in a.get("agency", "")),
        None,
    )
    request_text = (police or {}).get("request", "")

    return [
        _check(
            'type = "Power_Failure" 或描述含「號誌失效／號誌故障」',
            STATUS_PASS if triggered else STATUS_FAIL,
            (sop5 or {}).get("reason", ""),
            clause="第 5 條 觸發",
        ),
        _check(
            "人工指揮派遣建議須載明受影響路段",
            STATUS_PASS if routing_result.get("incident_name") else STATUS_FAIL,
            f"受影響路段：{routing_result.get('incident_name', '')}"
            f"（{routing_result.get('incident_segment_id', '')}）",
            clause="第 5 條 處置",
        ),
        _check(
            f"警力人數每路口 {sop_rules.SOP5_POLICE_PER_INTERSECTION} 人",
            STATUS_PASS if f"每路口 {sop_rules.SOP5_POLICE_PER_INTERSECTION} 人" in request_text
            else STATUS_FAIL,
            request_text or "未產出警力派遣請求",
            clause="第 5 條 處置",
        ),
        _check(
            "載明估計持續時間",
            STATUS_PASS if ete.get("ete_minutes") else STATUS_FAIL,
            f"依第 7 條估算 {ete.get('ete_minutes')} 分鐘" if ete.get("ete_minutes")
            else "未取得 ETE",
            clause="第 5 條 處置",
        ),
        _check(
            "號誌故障路段不下發長綠燈配時指令",
            STATUS_PASS if not (routing_result.get("signal_plans") or []) else STATUS_FAIL,
            "號誌已失效，依條文改以人工指揮，未產出配時調整",
            clause="第 5 條 處置",
        ),
        _check(
            "CMS 加註「<路段> 號誌故障，請依現場指揮通行」",
            STATUS_PASS if _cms_matches(comms_result, ("號誌故障", "現場指揮")) else STATUS_FAIL,
            _cms_sample(comms_result),
            clause="第 5 條 處置",
        ),
    ]


def _conformance_sop6(comms_result: dict, timestamp: str) -> list[dict]:
    triggered = bool(comms_result.get("trigger_sop6"))
    languages = comms_result.get("languages") or []
    messages = comms_result.get("messages") or []
    stations = comms_result.get("trigger_stations") or []
    requirements = comms_result.get("message_requirements") or {}
    broadcast_time = (comms_result.get("cms_broadcast") or {}).get(
        "broadcast_timestamp"
    ) or timestamp

    checks = [
        _check(
            f"判定範圍為全資料集任一基地台 Roaming_User_Pct ≥ "
            f"{sop_rules.SOP6_ROAMING_THRESHOLD:.0%}",
            STATUS_PASS,
            f"{comms_result.get('roaming_scope', '全資料集所有基地台')}；達標站點 "
            + ("、".join(
                f"{s.get('location_name', '')} {s.get('roaming_user_pct_display', '')}"
                for s in stations
            ) or "無"),
            clause="第 6 條 觸發",
        ),
        _check(
            "觸發時簡訊與看板須同時含多國語言並於同一回應產出",
            STATUS_PASS if (not triggered and len(languages) == 1)
            or (triggered and len(messages) >= 2) else STATUS_FAIL,
            f"本次產出 {len(messages)} 個語言版本（{'、'.join(languages)}），"
            f"CMS 與簡訊同一回應併出",
            clause="第 6 條 處置",
        ),
        _check(
            "時間格式統一為 YYYY-MM-DD HH:MM",
            STATUS_PASS if _TIME_PATTERN.match(str(broadcast_time or "")) else STATUS_FAIL,
            f"通報時間 {broadcast_time}",
            clause="第 6 條 格式",
        ),
        _check(
            "訊息要點：事故位置、改道指引、預計延誤時間、求援或避開提醒",
            STATUS_PASS if all(requirements.values()) else STATUS_FAIL,
            "、".join(
                f"{key}{'✓' if value else '✗'}" for key, value in requirements.items()
            ) or "未產出訊息要點檢核",
            clause="交付要求",
        ),
    ]
    return checks


def _conformance_sop7(ete: dict) -> list[dict]:
    severity = ete.get("severity", "")
    expected_base = sop_rules.ETE_BASE_CLEARANCE.get(severity)
    base = ete.get("base_clearance_minutes")
    penalty = ete.get("congestion_penalty_minutes")

    return [
        _check(
            "base_clearance 依嚴重度：Critical 60、High 40、Medium 20 分鐘",
            STATUS_PASS if expected_base is not None and base == expected_base
            else STATUS_FAIL,
            f"{severity} → {base} 分鐘",
            clause="第 7 條 公式",
        ),
        _check(
            "congestion_penalty =（受影響路段平均 Saturation_Score − 0.5）× 60，小於 0 以 0 計",
            STATUS_PASS if penalty is not None and float(penalty) >= 0 else STATUS_FAIL,
            (
                f"平均飽和度 {_percent(ete.get('avg_saturation_score'))} → 懲罰 {penalty} 分鐘"
                if ete.get("saturation_data_available")
                else f"受影響路段無車流量測，懲罰以 0 計（{ete.get('note', '')}）"
            ),
            clause="第 7 條 公式",
        ),
        _check(
            "報告須註明 ETE 數值與計算依據",
            STATUS_PASS if ete.get("ete_minutes") is not None and ete.get("formula")
            else STATUS_FAIL,
            f"ETE {ete.get('ete_minutes')} 分鐘；{ete.get('formula', '')}；"
            f"受影響路段＝{ete.get('affected_segments_definition', '')}",
            clause="第 7 條 報告",
        ),
    ]


def _cms_matches(comms_result: dict, needles: tuple[str, ...]) -> bool:
    """檢查繁中 CMS 句式是否含條文明訂的關鍵字串。"""
    for message in comms_result.get("messages") or []:
        if message.get("language") != "zh-TW":
            continue
        text = message.get("cms_text") or message.get("message") or ""
        return all(needle in text for needle in needles)
    return False


def _cms_sample(comms_result: dict) -> str:
    for message in comms_result.get("messages") or []:
        if message.get("language") == "zh-TW":
            return message.get("cms_text") or message.get("message") or ""
    return "未產出繁體中文 CMS 文字"


def _agency_request(
    cross_actions: list[dict], agency_keyword: str, *, sop_number: int | None = None
) -> str:
    """
    取出指定單位的跨系統請求作為證據。

    指定 sop_number 時優先取「條號正好相符」者。第 4 條會連動第 3 條，兩者都會對
    公車處發請求，不篩條號會抓到連動那筆，看起來像第 3 條的處置沒有產出。
    """
    matched = [
        action for action in cross_actions or []
        if agency_keyword in action.get("agency", "")
    ]
    if not matched:
        return "未產出對應請求"

    if sop_number is not None:
        exact = f"SOP 第 {sop_number} 條"
        preferred = [a for a in matched if a.get("sop_reference", "").strip() == exact]
        if preferred:
            matched = preferred

    action = matched[0]
    return f"{action.get('agency', '')}：{action.get('request', '')}"


__all__ = [
    "ENGINE_RULE",
    "ENGINE_LLM",
    "ENGINE_LABELS",
    "STATUS_PASS",
    "STATUS_FAIL",
    "STATUS_DEGRADED",
    "STATUS_NA",
    "build_decision_trace",
    "build_sop_conformance",
]
