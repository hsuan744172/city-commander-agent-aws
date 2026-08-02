# Implementation Plan：incident-injection-response

## Overview

本計畫以 Python 3.13／FastAPI 實作後端，以 React 19／JavaScript 實作前端；採契約與純 domain core 優先、再接生命週期/API、AI fallback、Monitoring bridge 與 UI，最後完成整合及 E2E。每個 leaf task 都可由 `spec-task-execution` agent 獨立執行，後續 wave 只依賴前序 wave 已完成的穩定介面。

## Tasks

- [x] 1. 建立事件領域契約、驗證與版本化教案
  - [x] 1.1 建立 incident response v1 套件與測試基礎
    - 建立 `backend/incident_response/` 與 `tests/backend/incident_response/` 結構、v1 feature flag、契約版本常數。
    - 在 `pyproject.toml`、`uv.lock` 以確切版本加入 Hypothesis 與測試依賴，設定可重現 pytest profile。
    - _Requirements: 12.2, 14.7_

  - [x] 1.2 實作 domain contracts、列舉、不可變模型與安全錯誤模型
    - 建立 Incident Payload/Record、Preview、Run、Snapshot、Deterministic Result、Decision Trace、CMS、Publication、Monitoring Alert 與 API error 模型。
    - 實作 UTC+8 時間解析/projection、Source Label、狀態與 fallback reason 列舉；strict model 不得靜默轉型。
    - _Requirements: 1.1, 3.1–3.7, 4.2, 9.8, 11.10, 12.2, 12.10, 12.11_

  - [x] 1.3 實作共用 payload parser、domain validator 與 preview 雜湊
    - 直接 JSON 與上傳共用頂層 shape、1–100 筆、原序、欄位、唯一分類、status、引用及重複 ID 驗證。
    - 實作 canonical JSON/SHA-256、聚合 index/path errors、malformed JSON 安全錯誤與 `.json`/UTF-8/1–1,048,576 bytes 規則。
    - _Requirements: 2.2–2.7, 3.1–3.21, 12.1, 12.7_

  - [x] 1.4 實作三個版本化 Scenario Preset registry 與 golden fixtures
    - 建立 `road-disruption/v1`、`crowd-surge/v1`、`signal-failure/v1` 唯讀 payload、摘要、版本與 golden deterministic JSON。
    - 加入 fixture hash/version 檢查；資料或 SOP 改變時須顯式升版或更新 golden。
    - _Requirements: 2.1, 2.8, 8.1, 8.4, 8.7, 14.2–14.4, 14.7, 14.8_

  - [ ]* 1.5 撰寫 Property 3 的 payload shape、數量與順序 property test
    - **Property 3: Payload Shape、數量與順序保存**
    - **Validates: Requirements 2.3, 2.4, 2.5, 2.6, 2.7, 12.1**
    - **PBT Metadata:** `framework=Hypothesis`; `test_file=tests/backend/incident_response/properties/test_property_03_payload_shape.py`; `minimum_examples=200`; `generators=event_sequences,top_level_shapes,canonical_json_bytes`; `oracle=shape/count/reference-order model`。

  - [ ]* 1.6 撰寫 Property 4 的嚴格事件欄位契約 property test
    - **Property 4: 嚴格事件欄位契約**
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.12, 3.15, 3.16**
    - **PBT Metadata:** `framework=Hypothesis`; `test_file=tests/backend/incident_response/properties/test_property_04_strict_contract.py`; `minimum_examples=200`; `generators=unicode_boundaries,wrong_types,calendar_datetimes,category_statuses`; `oracle=field-boundary/datetime round-trip model`。

  - [ ]* 1.7 撰寫 Property 5 的唯一分類與引用完整性 property test
    - **Property 5: 唯一分類與引用完整性**
    - **Validates: Requirements 3.8, 3.9, 3.10, 3.11, 3.13, 3.14, 3.17, 3.18, 3.19, 3.20**
    - **PBT Metadata:** `framework=Hypothesis`; `test_file=tests/backend/incident_response/properties/test_property_05_category_references.py`; `minimum_examples=200`; `generators=classification_predicates,known_unknown_ids,duplicate_batches`; `oracle=exactly-one predicate/reference-set model`。

  - [ ]* 1.8 撰寫 parser、preview 與 preset 邊界單元測試
    - 覆蓋 0/1/1,048,576/1,048,577 bytes、100/101 筆、閏年/非法日期、valid preview 後 invalid upload、stale confirmation。
    - 驗證三 fixture 各一筆且預覽含原序、category、位置、severity、時間與可能 SOP。
    - _Requirements: 2.1, 2.2, 2.8–2.11, 3.7, 3.21_

- [x] 2. 建立 Simulation Clock 與 immutable strict-as-of Snapshot
  - [x] 2.1 重構 Simulation Clock common timeline、command model 與 freeze leases
    - 由完整 Traffic/Crowd slice 升冪交集建立 timeline，實作 play/pause/tick/reset/authoritative now。
    - 實作 per-run 冪等 freeze lease/reference count，保存並恢復第一筆 freeze 前模式與時間；active run 時拒絕推進命令。
    - _Requirements: 1.10, 1.11, 5.1, 13.1–13.5, 13.13_

  - [x] 2.2 實作來源 loader、Complete Time Slice 驗證與 strict-as-of selection
    - 驗證 Traffic/Crowd 必要欄位、型別、slice ID 唯一；驗證 Road alternatives/nearby stations/capacity/intersections 引用。
    - 各來源選 `<= Effective_Event_Time` 最近完整 slice；禁止 interpolation、未來資料與退回未來最早資料。
    - _Requirements: 5.6–5.10, 13.1_

  - [x] 2.3 實作 Run-scoped SnapshotBundle 固定、版本與可用性證據
    - 首次 snapshot 深拷貝 records、actual time、availability/reason、schema/content hash、Road/SOP version，後續不受檔案/cache/clock 改變。
    - 提供 Effective Event Time、Simulation Clock time、逐來源時間/可用性的 Decision Trace 投影。
    - _Requirements: 5.2, 5.3, 5.5, 5.11, 5.12, 5.13_

  - [ ]* 2.4 撰寫 Property 2 的 Clock Freeze Lease property test
    - **Property 2: Clock Freeze Lease Round Trip**
    - **Validates: Requirements 1.10, 1.11, 13.13**
    - **PBT Metadata:** `framework=Hypothesis`; `test_file=tests/backend/incident_response/properties/test_property_02_clock_freeze.py`; `minimum_examples=200`; `generators=clock_modes,interleaved_leases,duplicate_commands`; `oracle=reference-counted freeze state machine`。

  - [ ]* 2.5 撰寫 Property 8 的 strict as-of selection property test
    - **Property 8: Strict As-of Snapshot 不使用未來資料**
    - **Validates: Requirements 5.6, 5.7, 5.8, 5.10**
    - **PBT Metadata:** `framework=Hypothesis`; `test_file=tests/backend/incident_response/properties/test_property_08_snapshot_asof.py`; `minimum_examples=200`; `generators=effective_times,complete_invalid_slices`; `oracle=max(t<=as_of) or unavailable`。

  - [ ]* 2.6 撰寫 Property 9 的來源驗證與 Snapshot 固定性 property test
    - **Property 9: 來源驗證與 Snapshot 固定性**
    - **Validates: Requirements 5.9, 5.11**
    - **PBT Metadata:** `framework=Hypothesis`; `test_file=tests/backend/incident_response/properties/test_property_09_snapshot_immutability.py`; `minimum_examples=150`; `generators=missing_fields,wrong_types,duplicate_ids,dangling_refs,mutations`; `oracle=source-validity plus immutable bytes`。

  - [ ]* 2.7 撰寫 Property 10 的未來情境隔離 property test
    - **Property 10: Future Simulation 隔離**
    - **Validates: Requirements 5.5**
    - **PBT Metadata:** `framework=Hypothesis`; `test_file=tests/backend/incident_response/properties/test_property_10_future_isolation.py`; `minimum_examples=100`; `generators=future_times,clock_modes,snapshot_timelines`; `oracle=event-as-of with unchanged global clock`。

  - [ ]* 2.8 撰寫 Property 24 的 common timeline/clock command property test
    - **Property 24: Common Timeline 與 Clock Command Model**
    - **Validates: Requirements 13.1, 13.2, 13.3**
    - **PBT Metadata:** `framework=Hypothesis`; `test_file=tests/backend/incident_response/properties/test_property_24_clock_commands.py`; `minimum_examples=200`; `generators=traffic_times,crowd_times,complete_flags,commands`; `oracle=sorted-set-intersection clock model`。

  - [ ]* 2.9 撰寫 repository 資料來源與 clock/snapshot 整合測試
    - 對現有 Traffic/Crowd/Road/SOP 執行 schema/hash/reference integrity 與 common timeline 檢查。
    - 驗證 snapshot 固定後來源替換/clock 推進不改變內容，且未來情境不改 global clock。
    - _Requirements: 5.1, 5.5–5.13, 13.1–13.5_

- [ ] 3. 實作 deterministic Response Engine、Decision Trace 與通報
  - [ ] 3.1 實作 SOP 2/3/5/6 三值判定與 typed evidence
    - 以純函式依固定 Incident/Snapshot/SOP versions 產生 `triggered|not_triggered|indeterminate` 與 observed/operator/threshold/outcome/missing inputs。
    - Engine 不得讀檔、讀 global clock、呼叫 AI 或修改輸入。
    - _Requirements: 6.1–6.9_

  - [ ] 3.2 實作 Road Disruption 候選、方向、穩定排序與路徑方案
    - 候選只取事故 alternatives 原序，實作 capacity、雙向相交、location/flow direction、排除理由及 `(saturation,segment_id)` 排序。
    - 實作 congestion exception、長綠燈/大眾運輸建議與無主候選 `unplannable`，不得虛構路線。
    - _Requirements: 7.1–7.13_

  - [ ] 3.3 實作 ETE 與 Crowd/Signal 差異化 deterministic actions
    - 實作 severity base、平均 saturation、壅塞加成與 unavailable/missing inputs。
    - 實作 Crowd 三項 recommended/not_recommended，以及 Signal intersections 去重與每路口 2 名警力。
    - _Requirements: 7.14–7.17, 8.3, 8.5, 8.6, 8.8_

  - [ ] 3.4 實作 CMS 多語 deterministic templates 與 facts validation
    - 依 nearby station roaming 決定繁中或四語；缺值時 SOP 6 為 indeterminate。
    - 每語言 ≤160 Unicode 字元且符合位置、指引、ETE/延誤事實；任一語言不一致則整組不可發布。
    - _Requirements: 8.9, 11.1–11.8, 11.12_

  - [ ] 3.5 組裝純 Response Engine、Decision Trace 與 Required Result evaluator
    - 將分類、SOP、路徑、ETE、actions、CMS 組成可重現結果，記錄 input versions 並排除牆鐘/AI 欄位。
    - 建立三類 Required Result schema、缺項與成功判定；Trace 僅含結構化證據。
    - _Requirements: 5.12, 6.1, 6.2, 9.11, 14.2–14.4, 14.7–14.9_

  - [ ]* 3.6 撰寫 Property 11 的 deterministic replay property test
    - **Property 11: Deterministic Result 可重現**
    - **Validates: Requirements 6.1, 6.2, 14.7**
    - **PBT Metadata:** `framework=Hypothesis`; `test_file=tests/backend/incident_response/properties/test_property_11_determinism.py`; `minimum_examples=150`; `generators=valid_incidents,immutable_snapshots,versions`; `oracle=deep equality/forbidden volatile fields`。

  - [ ]* 3.7 撰寫 Property 12 的 SOP 三值判定 property test
    - **Property 12: SOP 三值判定與證據**
    - **Validates: Requirements 6.3, 6.4, 6.5, 6.6, 6.7, 6.8**
    - **PBT Metadata:** `framework=Hypothesis`; `test_file=tests/backend/incident_response/properties/test_property_12_sop_evidence.py`; `minimum_examples=200`; `generators=boundary_values,missing_inputs,events`; `oracle=independent SOP three-valued model`。

  - [ ]* 3.8 撰寫 Property 13 的路徑來源與方向證據 property test
    - **Property 13: 路徑候選來源與方向證據**
    - **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.13**
    - **PBT Metadata:** `framework=Hypothesis`; `test_file=tests/backend/incident_response/properties/test_property_13_route_provenance.py`; `minimum_examples=200`; `generators=road_graphs,ordered_intersections,locations`; `oracle=alternative/intersection/direction model`。

  - [ ]* 3.9 撰寫 Property 14 的穩定選路 property test
    - **Property 14: 穩定選路、壅塞例外與不可規劃**
    - **Validates: Requirements 7.7, 7.8, 7.9, 7.10, 7.11, 7.12**
    - **PBT Metadata:** `framework=Hypothesis`; `test_file=tests/backend/incident_response/properties/test_property_14_route_selection.py`; `minimum_examples=200`; `generators=candidate_sets,saturation_ties,exclusions`; `oracle=eligibility conjunction/sorted tuple minimum`。

  - [ ]* 3.10 撰寫 Property 15 的 ETE 公式 property test
    - **Property 15: ETE 公式與可重算證據**
    - **Validates: Requirements 7.14, 7.15, 7.16, 7.17, 8.8**
    - **PBT Metadata:** `framework=Hypothesis`; `test_file=tests/backend/incident_response/properties/test_property_15_ete_formula.py`; `minimum_examples=200`; `generators=severities,saturation_lists,missing_inputs`; `oracle=base+max(0,(mean-0.5)*60)`。

  - [ ]* 3.11 撰寫 Property 16 的三類差異化動作 property test
    - **Property 16: 三類事件差異化動作**
    - **Validates: Requirements 8.3, 8.5, 8.6**
    - **PBT Metadata:** `framework=Hypothesis`; `test_file=tests/backend/incident_response/properties/test_property_16_category_actions.py`; `minimum_examples=150`; `generators=crowd_states,intersection_multisets`; `oracle=three-action truth table/2*unique count`。

  - [ ]* 3.12 撰寫 Property 18 的 CMS 語言與事實 property test
    - **Property 18: CMS 語言集合、長度與事實一致性**
    - **Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 11.8, 11.12**
    - **PBT Metadata:** `framework=Hypothesis`; `test_file=tests/backend/incident_response/properties/test_property_18_cms_messages.py`; `minimum_examples=200`; `generators=nearby_lists,roaming_maps,deterministic_facts`; `oracle=language threshold/Unicode length/facts allow-list`。

  - [ ]* 3.13 撰寫 Property 26 的 Decision Trace 安全完整性 property test
    - **Property 26: Decision Trace 完整且不含私有推理**
    - **Validates: Requirements 5.12, 9.11**
    - **PBT Metadata:** `framework=Hypothesis`; `test_file=tests/backend/incident_response/properties/test_property_26_trace_safety.py`; `minimum_examples=100`; `generators=snapshots,results,unavailable_sources`; `oracle=required fields/forbidden private fields`。

  - [ ]* 3.14 撰寫 Property 27 的 Required Result 完整性 property test
    - **Property 27: Required Result 完整性決定逐事件成功**
    - **Validates: Requirements 14.2, 14.3, 14.4, 14.8, 14.9**
    - **PBT Metadata:** `framework=Hypothesis`; `test_file=tests/backend/incident_response/properties/test_property_27_required_results.py`; `minimum_examples=150`; `generators=category_results,field_deletions,isolated_runs`; `oracle=category required schema/cross-run isolation`。

  - [ ]* 3.15 撰寫三個 preset golden 與 Response Engine example tests
    - 驗證 Road 主/次路徑、壅塞例外、ETE 70；Crowd 31,000、三項分流、ETE unavailable；Signal 三路口/6 警力/ETE 36.8/四語。
    - 覆蓋無次要路徑、不可規劃、缺來源與 category-specific 結果。
    - _Requirements: 7.1–7.17, 8.1–8.10, 14.2–14.5_

- [ ] 4. 建立 Incident Run lifecycle、Demo Session Store 與 API v1
  - [ ] 4.1 實作 concurrency-safe Demo Session Store 與狀態交易
    - 在單一 lock 保存 run、preview、idempotency/promotion indexes、history、publication、threshold state；terminal immutable。
    - 實作 transition CAS、最近 100 筆、延遲 eviction、replay provenance 與無 active run 才可 reset。
    - _Requirements: 4.2–4.8, 4.20, 10.7, 10.8, 10.11, 10.14, 12.5, 12.6, 14.10_

  - [ ] 4.2 實作 lifespan Run Coordinator、階段計時與 deadline 封箱
    - 實作 bounded queue/tasks、event isolation、clock lease、stage durations、progress。
    - 用 fakeable monotonic clock 實作 AI 15 秒、55 秒 fallback、58 秒 terminal resolution、shutdown/late-result guard。
    - _Requirements: 4.1, 4.9–4.20, 9.6, 9.7, 9.10, 14.5_

  - [ ] 4.3 實作 preset、JSON 與 upload preview API
    - 建立 preset list、JSON/upload preview endpoints，共用 parser 並回 ID/hash、摘要、future flags、required confirmations。
    - invalid 新內容不覆蓋 valid preview；內容/version 改變使確認失效；preview 不建 run/freeze。
    - _Requirements: 2.1–2.11, 5.4, 5.13, 12.1–12.3_

  - [ ] 4.4 實作 run 受理、查詢、歷程、重播與 reset API
    - 建立 run POST、單筆/列表 GET、replays/reset；1 秒內回 202、Location、Source Label、count、UTC+8 時間。
    - 實作 canonical idempotency、409 conflict、future confirmation、partial projection、固定歷史與 reset conflict。
    - _Requirements: 1.4, 1.5, 4.1, 4.9, 10.7–10.14, 12.3–12.6, 12.9–12.11_

  - [ ] 4.5 實作 API projection、統一錯誤 envelope 與安全 redaction
    - 所有 body 帶 contract `1.0`；4xx 有 stable code/path/message，5xx 僅 trace ID，不含 stack/credential/path/vendor text。
    - 保持事件原序、status/count/fallback；時間統一 UTC+8 並明示 `UTC+08:00`。
    - _Requirements: 3.20, 3.21, 4.19, 12.2, 12.7–12.11_

  - [ ]* 4.6 撰寫 Property 6 的 Run 狀態機 property test
    - **Property 6: Incident Run 狀態機安全性**
    - **Validates: Requirements 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8**
    - **PBT Metadata:** `framework=Hypothesis`; `test_file=tests/backend/incident_response/properties/test_property_06_run_state_machine.py`; `minimum_examples=200`; `generators=state_target_pairs,command_sequences`; `oracle=transition adjacency table`。

  - [ ]* 4.7 撰寫 Property 7 的 deadline/terminal resolution property test
    - **Property 7: Deadline 與 Terminal Status 決議**
    - **Validates: Requirements 4.10, 4.11, 4.12, 4.13, 4.15, 4.16, 4.17, 4.18, 4.19, 4.20, 9.10**
    - **PBT Metadata:** `framework=Hypothesis`; `test_file=tests/backend/incident_response/properties/test_property_07_terminal_resolution.py`; `minimum_examples=200`; `generators=completion_vectors,fallback_flags,elapsed_boundaries,late_mutations`; `oracle=55/58-second truth table/immutability`。

  - [ ]* 4.8 撰寫 Property 20 的 canonical idempotency property test
    - **Property 20: Canonical Idempotency**
    - **Validates: Requirements 12.5, 12.6**
    - **PBT Metadata:** `framework=Hypothesis`; `test_file=tests/backend/incident_response/properties/test_property_20_idempotency.py`; `minimum_examples=200`; `generators=key_permutations,trimmable_strings,event_orders,keys`; `oracle=canonical-hash equivalence/conflict model`。

  - [ ]* 4.9 撰寫 Property 21 的歷程與 replay property test
    - **Property 21: 歷程上限與 Replay 關聯**
    - **Validates: Requirements 10.7, 10.8, 10.11**
    - **PBT Metadata:** `framework=Hypothesis`; `test_file=tests/backend/incident_response/properties/test_property_21_history_replay.py`; `minimum_examples=120`; `generators=run_sequences_over_100,replay_targets`; `oracle=latest-100/fixed provenance model`。

  - [ ]* 4.10 撰寫 Property 22 的 Demo Reset property test
    - **Property 22: Demo Reset 原子重設**
    - **Validates: Requirements 10.14, 14.10**
    - **PBT Metadata:** `framework=Hypothesis`; `test_file=tests/backend/incident_response/properties/test_property_22_demo_reset.py`; `minimum_examples=100`; `generators=session_states,active_counts,populated_indexes`; `oracle=all-or-nothing initial state`。

  - [ ]* 4.11 撰寫 Property 25 的 API projection/安全錯誤 property test
    - **Property 25: API Projection、時間與安全錯誤**
    - **Validates: Requirements 3.21, 12.2, 12.7, 12.8, 12.9, 12.10, 12.11**
    - **PBT Metadata:** `framework=Hypothesis`; `test_file=tests/backend/incident_response/properties/test_property_25_api_projection.py`; `minimum_examples=150`; `generators=runs,partial_results,aware_datetimes,sensitive_errors`; `oracle=domain projection/UTC+8/secret deny-list`。

  - [ ]* 4.12 撰寫 API v1 contract 與 OpenAPI snapshot tests
    - 驗證 presets/preview/upload/accept/query/history/replay/reset schema、202/Location、4xx/5xx、idempotency、terminal immutability。
    - 鎖定 v1 OpenAPI/JSON Schema，驗證 partial 原序與 accepted latency 量測介面。
    - _Requirements: 4.1, 4.9, 4.14, 12.1–12.11_

- [ ] 5. 實作 AI fallback、模擬發布與可觀測性
  - [ ] 5.1 實作 AI Narrative Adapter、Consistency Gate 與 fallback renderer
    - 僅傳 Deterministic Result/SOP facts/schema；strict parse ≤500 字繁中 narrative/claims，對 SOP/ID/數值/時間/路徑/ETE/動作做 allow-list。
    - 實作 15 秒 timeout/cancel、四種 fallback reason、deterministic template、terminal/version guard；隱藏 vendor error，AI 不得改決策。
    - _Requirements: 6.10, 6.11, 9.1–9.10, 14.5_

  - [ ] 5.2 實作 Simulated Publish domain service 與 API
    - 建立 publication endpoint/message-version guard，只允許 publishable 語言；原子記錄全部選定語言、run、內容與 UTC+8 時間。
    - 任一驗證/寫入失敗不留 record；固定回 `Simulated_Publish－未連接真實通路`。
    - _Requirements: 8.9, 11.9–11.11_

  - [ ] 5.3 實作結構化 operational logs、metrics hooks 與敏感資訊遮罩
    - 以 trace/run/event ID 記 transition、duration、fallback、versions、counts、latency、AI/error、idempotency metrics。
    - 禁止完整 upload/prompt/credential/private path/stack/vendor body，提供可測 log/metrics sink。
    - _Requirements: 4.19, 9.7, 12.8_

  - [ ]* 5.4 撰寫 Property 17 的 AI claims/fallback property test
    - **Property 17: AI Claims Gate 與 Fallback**
    - **Validates: Requirements 6.10, 6.11, 9.1, 9.2, 9.3, 9.5, 9.8**
    - **PBT Metadata:** `framework=Hypothesis`; `test_file=tests/backend/incident_response/properties/test_property_17_ai_claims.py`; `minimum_examples=200`; `generators=fact_sets,claim_subsets_conflicts,unicode_text`; `oracle=facts subset/language/length gate`。

  - [ ]* 5.5 撰寫 Property 19 的發布原子性 property test
    - **Property 19: Simulated Publish 原子性**
    - **Validates: Requirements 11.10, 11.11**
    - **PBT Metadata:** `framework=Hypothesis`; `test_file=tests/backend/incident_response/properties/test_property_19_publish_atomicity.py`; `minimum_examples=150`; `generators=language_sets,validation_failures,write_faults`; `oracle=single-record all-or-nothing model`。

  - [ ]* 5.6 撰寫 AI timeout/error/late result 與 observability 整合測試
    - 以 fake adapter/clock 驗證 valid AI、15 秒 timeout、service error、consistency failure、55 秒 deadline、terminal 後 late return。
    - 掃描 API/log/metrics，確認無 vendor body、credential、prompt、stack、絕對路徑。
    - _Requirements: 4.11–4.20, 9.4–9.10, 12.8, 14.5_

- [ ] 6. 建立 Monitoring Alert bridge 與模組一時間整合
  - [ ] 6.1 實作 threshold crossing/rearm detector 與 Monitoring Alert store
    - 每路段分別維護 0.85 B 級/0.95 A 級 armed bit，只在 `< threshold` 到 `>= threshold` 建 alert，降回下方才 rearm。
    - 固定保存前後值、threshold、level、data time、唯一 ID、`time_series_alert` Source Label。
    - _Requirements: 1.1, 1.3, 13.5–13.11_

  - [ ] 6.2 實作 Monitoring Alert 升級 preview、確認與天然冪等
    - 由 alert 預填時間、segment、前後 saturation、門檻、alert ID；明確確認後才建 `monitoring_promotion` Run。
    - 重複升級回首次 run；保留 provenance，不改 alert/rearm state，並區隔 scenario/json source。
    - _Requirements: 1.4–1.9, 5.2, 13.12, 13.14_

  - [ ] 6.3 實作 Monitoring/Clock v1 endpoints 與 dashboard bridge projection
    - 提供 clock query/play/pause/reset、alerts query、promotion preview；active run 時拒絕推進。
    - 既有 dashboard 使用同一 common slice，回 Traffic/Crowd 與 alert 關聯。
    - _Requirements: 5.1, 13.3–13.5, 13.12–13.14_

  - [ ]* 6.4 撰寫 Property 1 的來源/確認/升級追溯 property test
    - **Property 1: 來源、確認與升級可追溯性**
    - **Validates: Requirements 1.1, 1.4, 1.5, 1.6, 1.8, 1.9, 5.2, 5.3, 13.14**
    - **PBT Metadata:** `framework=Hypothesis`; `test_file=tests/backend/incident_response/properties/test_property_01_source_provenance.py`; `minimum_examples=200`; `generators=preview_sources,confirm_commands,alerts,repeated_promotions`; `oracle=confirmed-once provenance model`。

  - [ ]* 6.5 撰寫 Property 23 的 threshold crossing/rearm property test
    - **Property 23: Monitoring Alert Crossing 與 Rearm**
    - **Validates: Requirements 1.3, 13.6, 13.7, 13.8, 13.9, 13.10, 13.11**
    - **PBT Metadata:** `framework=Hypothesis`; `test_file=tests/backend/incident_response/properties/test_property_23_monitoring_alerts.py`; `minimum_examples=200`; `generators=segment_saturation_sequences`; `oracle=per-threshold armed-bit state machine`。

  - [ ]* 6.6 撰寫 clock tick → alert → promotion → run 整合測試
    - 驗證 common slice 更新 Traffic/Crowd、crossing 不重複、promotion 需確認、run freeze/terminal 恢復。
    - 驗證注入不改 alert，歷史保留 run-alert-slice 關聯。
    - _Requirements: 1.3–1.11, 13.4–13.14_

- [ ] 7. 實作前端預覽、確認與執行進度
  - [ ] 7.1 建立 Incident v1 API client、typed view model 與 reducer
    - 建立 `empty→preview_valid→accepted/running→terminal/history`、錯誤 mapping、poll cancellation/retry/stale indicator。
    - 分離 valid preview 與新檔錯誤；內容/version 改變清 confirmation；所有 alert/run 顯示 Source Label。
    - _Requirements: 1.2, 2.9–2.11, 4.9, 10.1, 12.3, 12.4_

  - [ ] 7.2 實作 preset/JSON preview、future simulation 與明確確認 UI
    - 提供三 preset 卡、`.json` drop zone、數量/原序/category/位置/severity/時間/可能 SOP/errors。
    - 未來事件顯示預演標示並額外確認；取消不呼叫 run；reset 後兩次操作內可見 preset preview。
    - _Requirements: 1.7, 2.1, 2.2, 2.8–2.11, 5.4, 5.13, 14.1_

  - [ ] 7.3 實作 run 受理、每秒輪詢與 60 秒進度 UI
    - 顯示 run ID、Source Label、stage、完成/總數、elapsed/60 秒；短暫失敗保留狀態並 1/2 秒 capped retry。
    - API 狀態可查後 2 秒內更新，terminal 停止輪詢並切固定結果。
    - _Requirements: 4.9, 4.14, 10.1, 12.4_

  - [ ]* 7.4 撰寫 preview/confirmation/progress React component tests
    - 覆蓋 valid 後 invalid、future confirmation、取消、內容改變、來源標籤、stage/progress、retry/stale、terminal stop。
    - 驗證 reset 後兩次操作 preview 與 UI 2 秒更新控制。
    - _Requirements: 1.2, 1.5, 1.7, 2.8–2.11, 4.9, 5.4, 10.1, 14.1_

- [ ] 8. 實作前端結果、地圖、歷程與發布
  - [ ] 8.1 實作多事件切換與三類差異化結果區塊
    - 依原始 index 建 tabs；分開 Deterministic Result、Decision Trace、AI/SOP 備援說明。
    - 顯示 Road 路徑/排除/號誌/ETE/CMS、Crowd 證據/分流/動作、Signal 路口/警力/時間/CMS 與對應完成訊息。
    - _Requirements: 8.1–8.10, 9.4, 9.9, 9.12, 10.2, 14.2–14.5_

  - [ ] 8.2 實作事件/路徑地圖與完全本地降級路網
    - 擴充 bundled geometry，標事故紅、主綠、次藍虛線、壅塞橘、站點紫、不可用灰圖例。
    - tile 失敗切 local SVG/canvas；無座標/歷史 geometry 缺失顯示原因，不用目前資料替代。
    - _Requirements: 10.3–10.6, 10.10, 10.12, 14.6_

  - [ ] 8.3 實作最近 100 筆歷程、唯讀還原與 replay UI
    - 新至舊顯示 history，唯讀呈現固定 input/snapshot/trace/narrative/CMS/publication。
    - Replay 建新 run ID 並顯示 provenance，不修改原歷史。
    - _Requirements: 10.7–10.11, 13.14, 14.8_

  - [ ] 8.4 實作 Simulated Publish 與 Demo Reset UI
    - 僅允許通過 facts validation 的語言；確認/完成固定顯示 `Simulated_Publish－未連接真實通路`；失敗保持全未發布。
    - active run disable reset；成功後清 preview/confirmation/history/publish cache 並重抓 clock。
    - _Requirements: 8.9, 10.13, 10.14, 11.9–11.11, 14.10_

  - [ ] 8.5 將 v1 Incident 戰情頁、Monitoring 升級入口與既有 App 完整接線
    - 組裝 preview/progress/results/map/history/replay/publish/reset，並保留 legacy feature flag 回退。
    - Dashboard alert 提供明確升級與預填，維持兩模組 Source Label、clock/snapshot 關聯。
    - _Requirements: 1.2, 1.7, 10.1–10.14, 13.12–13.14_

  - [ ]* 8.6 撰寫結果、地圖、歷程、發布與 reset React tests
    - 覆蓋三 category、fallback、原序 tabs、座標、無 secondary、congestion、tile/local map、history missing-data。
    - 覆蓋 replay 新 ID、publish 警語/原子視圖、active reset disabled、reset 清狀態。
    - _Requirements: 8.1–8.10, 9.4, 9.9, 9.12, 10.2–10.14, 11.9–11.11, 14.6_

- [ ] 9. 完成後端接線、整合與 E2E 驗證
  - [ ] 9.1 將 Store、Coordinator、Clock、Snapshot、Engine、AI、Monitoring 與 v1 routers 接入 FastAPI lifespan
    - 更新 application factory/startup/shutdown 與 single-process health guard，所有 mutation 共用 Demo Session 一致性邊界。
    - 保留 legacy/feature flag；v1 不走舊 interpolation、forced-route、AI-error-as-narrative。
    - _Requirements: 1.10, 4.1–4.20, 5.1, 6.1–6.11, 12.1–12.11_

  - [ ]* 9.2 撰寫完整後端整合與 fault-injection tests
    - 驗證 preview→accept→terminal、partial、freeze、55/58 秒、history/replay、promotion、publish rollback、reset。
    - 驗證 snapshot 固定、100 events bounded、accepted <1 秒、terminal immutable、Required Result 缺項。
    - _Requirements: 1.4–1.11, 4.1–4.20, 5.6–5.12, 10.7–10.14, 11.10–11.11, 14.2–14.10_

  - [ ]* 9.3 撰寫瀏覽器 E2E 的三 preset normal/fallback/offline matrix
    - 自動化 reset/preview/confirm 三 preset；在 normal AI、timeout、service error 驗證 60 秒內 Required Results/進度/耗時。
    - 攔截外網/tile，驗證 trace/local map/history/replay/publish；accepted <1 秒、狀態可查後 UI <2 秒。
    - _Requirements: 4.1, 4.9, 4.14, 14.1–14.6_

  - [ ]* 9.4 撰寫輸入安全、效能邊界與離線回歸自動測試
    - fuzz malformed JSON、Unicode/XSS、oversized upload、log redaction；確認 React escaping 且不以 `dangerouslySetInnerHTML` 呈現上傳。
    - 驗證 1/3/100 events timing、無 Bedrock/公網、OpenAPI/golden/source hashes 不漂移。
    - _Requirements: 2.2, 3.21, 4.1, 9.6, 9.7, 12.7, 12.8, 14.5–14.7_

- [ ] 10. Checkpoint－確認所有自動測試與建置通過
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- 標示 `*` 的測試 sub-task 為 optional；未標示者是 MVP 核心實作，不可略過。
- Property 1–27 各有一個獨立 Hypothesis task，metadata 明列 framework、test file、minimum examples、generators、oracle。
- Required Result、數值、路徑、SOP、CMS facts 均由 deterministic layer 形成；AI 只做經驗證敘事。
- 僅包含可由 coding agent 完成的寫入、修改或自動測試工作；不含部署、人工驗收、文件或組織流程。
- DAG 稽核結果：70 個 incomplete leaf tasks 全部且僅出現一次，14 個 wave ID 由 0 連續至 13；所有相依均由低 wave 指向高 wave，因此無循環。Requirements 1–14 與設計列出的 MVP 範圍皆有實作或自動測試 leaf task。

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["1.3", "2.1", "2.2"] },
    { "id": 3, "tasks": ["1.4", "1.5", "1.6", "1.7", "2.3", "2.4", "2.5", "2.8"] },
    { "id": 4, "tasks": ["1.8", "2.6", "2.7", "2.9", "3.1", "3.2", "3.3", "3.4", "4.1", "6.1"] },
    { "id": 5, "tasks": ["3.5", "3.7", "3.8", "3.9", "3.10", "3.11", "3.12", "4.3", "4.6", "4.8", "4.9", "4.10", "5.2", "6.2", "6.5"] },
    { "id": 6, "tasks": ["3.6", "3.13", "3.14", "3.15", "4.2", "5.1", "5.5", "6.4"] },
    { "id": 7, "tasks": ["4.4", "4.7", "5.4"] },
    { "id": 8, "tasks": ["4.5", "5.6", "6.3", "6.6"] },
    { "id": 9, "tasks": ["4.11", "5.3", "7.1", "9.1"] },
    { "id": 10, "tasks": ["4.12", "7.2", "7.3", "8.1", "8.2", "8.3", "8.4", "9.2"] },
    { "id": 11, "tasks": ["7.4", "8.5"] },
    { "id": 12, "tasks": ["8.6"] },
    { "id": 13, "tasks": ["9.3", "9.4"] }
  ]
}
```
