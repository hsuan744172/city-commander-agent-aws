# Requirements Document

## 文件狀態

- 規格名稱：`incident-injection-response`
- 工作流程：Requirements-First
- 目前階段：Requirements
- 主要範圍：模組二「突發事件注入與處置」
- 整合範圍：模組一「動態時序監測儀錶板」與未來後端模擬時間
- 非本階段工作：不修改產品程式碼、不建立技術設計、不拆解實作任務

## Introduction

本功能將「突發事件注入」定位為競賽 Demo／POC 的受控演練入口：管理員可預覽並注入教案事件，系統依事件發生時間取得一致的車流、人流、路網及交通應變規則，於 60 秒內呈現可追溯的處置結果。系統以程式規則負責門檻、路徑與時間估算，以生成式 AI 負責有依據的事件解讀、專業建議書與公眾訊息；即使生成式 AI 暫時不可用，Demo 仍須呈現規則運算結果。

本功能同時建立兩個模組的清楚邊界：模組一依時間序列與規則門檻主動發現異常，模組二依管理員注入的外生事件啟動完整處置。兩者共用後端管理的模擬時間與資料快照，但不得混淆事件來源或重複觸發。

## Glossary

- **City_Commander_System**：涵蓋監測、事件處置、策略諮詢、決策解釋與公眾通報的整體城市應變系統。
- **Monitoring_Dashboard**：模組一；依模擬時間展示車流與人流時序資料，並依 SOP 門檻產生自動預警。
- **Incident_Response_System**：模組二；接收、驗證及處理突發事件，並產出處置結果與歷程。
- **Incident_Response_UI**：模組二的前端操作介面，提供教案選擇、JSON 預覽、注入進度、地圖、建議書及歷程。
- **Incident_Response_API**：模組二的後端介面，負責事件驗證、受理、狀態查詢與結果回傳。
- **Response_Engine**：依 SOP 與資料快照完成事件分類、路徑、ETE、通報及建議書資料彙整的處理元件。
- **Simulation_Clock**：由後端控制的模擬時間來源，提供目前時間、播放、暫停、重設與時間推進狀態。
- **Effective_Event_Time**：單一事件進行規則判定及資料取樣時採用的有效時間。
- **Data_Snapshot**：在 Effective_Event_Time 可取得且不晚於該時間的最近一筆完整來源資料，並保留實際資料時間。
- **Complete_Time_Slice**：單一來源在特定時間至少包含一筆紀錄，且該時間的全部紀錄均通過必要欄位、型別及識別碼完整性檢查的時間切片。
- **Monitoring_Alert**：由 Monitoring_Dashboard 比較同一指標的前一個與目前 Data_Snapshot，並在數值由門檻下方跨越至門檻值以上時產生的預警。
- **Injected_Incident**：由管理員透過教案或 JSON 明確提交的外生突發事件；Injected_Incident 不代表 Monitoring_Dashboard 已觀測到門檻跨越。
- **Source_Label**：Incident_Run 唯一且可見的來源標記，允許值為 `time_series_alert`、`scenario_preset`、`json_upload` 或 `monitoring_promotion`。
- **Incident_Payload**：送入 Incident_Response_System 的 JSON 文件，頂層僅可為非空事件陣列，或僅以非空 `incidents` 陣列承載事件的物件。
- **Incident_Record**：Incident_Payload 中的單一事件，包含必填的 `event_id`、`type`、`location`、`affected_segment`、`severity`、`description` 與 `timestamp`，以及依 Event_Category 規定的 `status`。
- **Event_Category**：依 `type` 與 `affected_segment` 判定的 `Road_Disruption`、`Crowd_Surge` 或 `Signal_Failure` 類別。
- **Scenario_Preset**：系統內建、版本化且可在注入前預覽的競賽教案事件。
- **Incident_Run**：一次事件注入所建立的可追蹤處理執行，具有唯一識別碼、狀態、時間戳、Source_Label、輸入摘要及輸出。
- **Idempotency_Key**：由呼叫端提供的重試識別值；同一 Idempotency_Key 在相同契約版本下只能對應一份正規化 Incident_Payload。
- **Terminal_Status**：Incident_Run 不再轉移的終止狀態，包含 `completed`、`completed_with_fallback`、`completed_with_partial_failure` 與 `failed`。
- **Demo_Session**：從 Demo 重設開始到下一次重設之間的操作期間。
- **SOP**：`emergency_traffic_sop.txt` 定義的七條交通應變標準程序；在本 POC 中為門檻與處置規則的權威來源。
- **Traffic_Snapshot**：從 `city_traffic_flow.csv` 取得的路段時速、車數、飽和度與車道狀態資料。
- **Crowd_Snapshot**：從 `signaling_crowd_density.csv` 取得的站點人數、成長率與漫遊率資料。
- **Road_Network**：`road_network_geometry.json` 定義的單向替代路線、容量、相交路段、流向與鄰近基地台資料。
- **Road_Disruption**：影響 `RD_` 路段的道路事故或路面塌陷事件，對應 SOP 第 2 條。
- **Crowd_Surge**：影響 `BS_` 站點的人群推擠或異常聚集事件，對應 SOP 第 3 條。
- **Signal_Failure**：影響 `RD_` 路段，且 `type` 為 `Power_Failure` 或描述包含 SOP 第 5 條號誌故障關鍵詞的事件，對應 SOP 第 5 條。
- **Deterministic_Result**：由程式依輸入資料與 SOP 計算的事件分類、門檻、路徑、排除理由、號誌建議、跨系統動作及 ETE。
- **Required_Result**：Requirement 14 依 Event_Category 列出的必要驗收輸出；Incident_Record 只有在全部 Required_Result 已形成時才計為成功。
- **AI_Narrative**：生成式 AI 依 Deterministic_Result 與 SOP 證據產出的專業自然語言說明。
- **Decision_Trace**：可供評審核對的輸入值、規則、候選方案、排除理由及計算結果；Decision_Trace 不包含模型私有思考鏈。
- **Fallback_Mode**：生成式 AI 超時或失敗時，以 Deterministic_Result 與固定模板完成畫面更新的降級模式。
- **ETE**：依 SOP 第 7 條計算的預計交通恢復時間。
- **CMS_Message**：適合電子看板與手機簡訊呈現的公眾通報文字。
- **Simulated_Publish**：POC 內記錄發布操作但不連接真實 CMS、簡訊或交通控制設備的展示行為。

## 依據與現況分析

### 已檢視依據

1. `（中華電信）命題文件 - 2026 雲湧智生：臺灣生成式 AI 應用黑客松競賽.pdf`
2. `（中華電信）命題解說 - 2026 雲湧智生：臺灣生成式 AI 應用黑客松競賽.pdf`
3. `中華電信 - 黑客松企業數據工作坊簡報.pdf`
4. `city_traffic_flow.csv`、`signaling_crowd_density.csv`、`road_network_geometry.json`、`emergency_traffic_sop.txt`
5. 現有 FastAPI、代理程式、事件上傳頁、處置卡片與地圖元件

競賽文件把 `live_incidents.json` 列為第五份動態事件資料，並指定路面塌陷、人群推擠、號誌故障三類事件分別對應 SOP 第 2、3、5 條；目前 workspace 未包含該檔案，因此本規格要求以明確契約與三個 Scenario_Preset 補足可重現教案，而不假設缺失檔案中的未公開欄位。

### 模組關聯、責任邊界與資料流

| 面向 | 模組一：Monitoring_Dashboard | 模組二：Incident_Response_System |
|---|---|---|
| 主要目的 | 從早到晚主動監測趨勢並在跨越門檻時預警 | 注入外生事件並演示完整應變決策 |
| 觸發來源 | Traffic_Snapshot、Crowd_Snapshot 與 SOP 門檻 | Scenario_Preset 或管理員提供的 Incident_Payload |
| 事件語意 | 「數據已達異常條件」 | 「已發生明確事故、推擠或故障」 |
| 人工操作 | 不需人工查詢；可檢視或明確升級處理 | 必須預覽、確認並注入，或明確接收模組一升級 |
| 共用內容 | Simulation_Clock、Data_Snapshot、SOP、Road_Network、Response_Engine | Simulation_Clock、Data_Snapshot、SOP、Road_Network、Response_Engine |
| 主要輸出 | Monitoring_Alert、趨勢、門檻證據、必要的自動引導 | Incident_Run、Decision_Trace、地圖方案、建議書、CMS_Message、處置歷程 |
| 邊界 | 不得把每次輪詢重複視為新事故 | 不得偷偷推進 Simulation_Clock 或把注入事件偽裝成時序自動發現 |

**模組一資料流：** Simulation_Clock → 時序資料取樣 → 程式門檻判定 → Monitoring_Alert → AI 摘要 → 儀錶板。

**模組二資料流：** Scenario_Preset／Incident_Payload → 預覽與驗證 → 建立 Incident_Run → 依 Effective_Event_Time 取得 Data_Snapshot → SOP 判定與程式計算 → AI_Narrative／Fallback_Mode → 地圖、建議書、CMS_Message 與歷程。

**整合資料流：** Monitoring_Alert 可由管理員明確升級為 Injected_Incident；升級後沿用原預警的資料時間與證據，另建立 Incident_Run 並保留 `monitoring_promotion` 來源。

### 模組一自動預警與模組二事件注入的差異

1. 模組一的 B 級／A 級預警是觀測值跨越 0.85／0.95 等 SOP 門檻的結果；模組二的 Road_Disruption 可在尚未跨越壅塞門檻時，因 `status`、`severity` 與受影響路段符合 SOP 第 2 條而啟動處置。
2. 模組一應隨 Simulation_Clock 自動運行；模組二應由管理員或明確升級動作啟動。
3. 模組一回答「何時開始異常」；模組二回答「事故發生後如何處置、為何如此處置、處置到哪一步」。
4. 命題文件提到「佔有率 ≥ 85% 且持續 ≥ 5 分鐘」與「單站人流 5 分鐘增幅 ≥ 50%」作為可量化注入範例；正式判定仍應引用目前提供的 SOP 條款，不得以範例取代 SOP。
5. 兩個模組可共用 Response_Engine，但事件來源、觸發規則、歷程與畫面標籤必須可區辨。

### 現有實作檢視與適合調整處

| 現況 | 風險／限制 | 適合調整方向 |
|---|---|---|
| `/api/status` 固定選擇資料筆數最多且最晚的時間切片 | 儀錶板停在單一晚間狀態，無法展示從早到晚自動預警 | 由 Simulation_Clock 決定取樣時間，模組一與模組二共用時間語意 |
| 模組一目前只呈現車流，且每 30 秒輪詢 | 未完整展示命題要求的車流與人流融合 | 加入 Crowd_Snapshot 與門檻跨越事件，避免每次輪詢重複告警 |
| workspace 沒有 `live_incidents.json` | Demo 無可重現的官方注入檔 | 建立版本化 Incident_Payload 契約及三類 Scenario_Preset；若後續取得官方檔案再做相容性確認 |
| 上傳介面只支援檔案拖放 | 評審無法快速理解或穩定重播三類案例 | 增加內建教案、預覽、確認、Demo 重設與重播 |
| 上傳 API 直接將原始 dict 送入處理器 | 上傳路徑繞過 `Incident` 模型，空值、列舉與跨欄位一致性未驗證 | 讓檔案上傳與 JSON API 共用同一驗證器與錯誤契約 |
| 多數 Incident 欄位預設為空字串 | 無效事件可能進入規則與 AI 流程 | 依事件類別定義必填欄位、允許值與路段／站點一致性 |
| 處理為同步呼叫，無執行狀態與端到端計時 | 無法證明 60 秒驗收，也無法清楚顯示卡在哪個階段 | 建立 Incident_Run、階段狀態、耗時量測與超時降級 |
| 事件時間找不到時使用最近資料，有些路徑只保留一列 | 可能使用未來資料或不完整路網切片 | 採不晚於事件時間的來源快照，回傳實際資料時間與完整性 |
| 上游判定以 intersections 陣列前半部推估 | 無法證明事故點相對位置，可能誤判 SOP 第 2 條 | 以事件位置、流向及有序 intersections 建立可追溯判定；資料不足時標記降級理由 |
| 主路徑可選到壅塞路段但畫面未完整列出排除清單 | 與命題「避開容量不足或已飽和路段」的驗收語意可能衝突 | 優先選非壅塞合格路段；全數壅塞時依 SOP 明確標記例外、長綠燈與大眾運輸建議 |
| 人流事件使用基地台 ID 計算道路平均飽和度 | ETE 可能以預設值產生看似精確但無有效路段依據的數字 | 只有具有效道路影響範圍時才計算 ETE，否則顯示不可計算與原因 |
| 成功訊息一律顯示「完成路網重規劃」 | 人流與號誌事件的結果描述不正確 | 依事件類別顯示路網、接駁分流或人工指揮成果 |
| 地圖座標只涵蓋部分路段與站點，且底圖依賴外部服務 | 某些教案無法定位，現場網路不穩時展示失敗 | 涵蓋資料集可引用位置，並提供無外部底圖時仍可讀的降級視圖 |
| AI 錯誤文字可能被當成 AI_Narrative | 畫面可能將供應商錯誤誤呈現為專業建議 | 以明確成功條件判斷 AI 輸出，失敗時使用 Fallback_Mode |
| 「發布 CMS」只更新前端記憶體狀態 | 容易讓觀眾誤認已連接真實通路，且無稽核紀錄 | 清楚標示 Simulated_Publish，記錄語言、時間與 Incident_Run |
| 沒有事件歷程、冪等或重播語意 | 重複點擊可能重複處理，評審無法查看處置過程 | 建立 Demo_Session 歷程、唯一執行識別、冪等受理與明確重播 |

## Requirements

### Requirement 1：Demo 定位與模組責任邊界

**User Story:** 作為競賽評審，我想清楚辨識系統主動預警與人工事件注入的差異，以便理解系統兼具自動感知及互動決策能力。

#### Acceptance Criteria

1. THE City_Commander_System SHALL 為每個 Monitoring_Alert 與 Incident_Run 指派唯一一個 Source_Label。
2. WHEN Incident_Response_UI 顯示 Monitoring_Alert 或 Incident_Run，THE Incident_Response_UI SHALL 顯示對應的 Source_Label。
3. WHEN 同一指標的目前 Data_Snapshot 數值由前一個 Data_Snapshot 的門檻下方跨越至門檻值以上，THE Monitoring_Dashboard SHALL 建立對應門檻的 Monitoring_Alert。
4. WHEN 管理員確認 Scenario_Preset、JSON 預覽或 Monitoring_Alert 升級，THE Incident_Response_System SHALL 建立獨立的 Incident_Run。
5. IF 管理員取消確認，THEN THE Incident_Response_System SHALL 保持 Incident_Run 數量不變。
6. WHEN Incident_Run 由 Monitoring_Alert 升級而來，THE Incident_Response_System SHALL 保留原始 Monitoring_Alert 識別碼、資料時間、門檻與比較值。
7. WHERE 啟用 Monitoring_Alert 升級功能，THE Incident_Response_UI SHALL 要求管理員執行一次明確確認。
8. WHEN 同一 Monitoring_Alert 被重複確認升級，THE Incident_Response_System SHALL 回傳首次升級建立的 Incident_Run。
9. WHEN Injected_Incident 被受理，THE Incident_Response_System SHALL 保持 Monitoring_Alert 的數量與門檻狀態不變。
10. WHILE 任一 Incident_Run 處於非 Terminal_Status，THE Incident_Response_System SHALL 凍結 Simulation_Clock 的目前時間與播放步進。
11. WHEN 最後一個非 Terminal_Status 的 Incident_Run 結束，THE Simulation_Clock SHALL 恢復凍結前的播放或暫停狀態。

### Requirement 2：事件注入形式與預覽

**User Story:** 作為 Demo 操作者，我想以內建教案或 JSON 檔快速注入事件，以便穩定展示三種官方情境。

#### Acceptance Criteria

1. THE Incident_Response_UI SHALL 提供各含一筆對應 Event_Category 事件的 Road_Disruption、Crowd_Surge 與 Signal_Failure Scenario_Preset。
2. THE Incident_Response_UI SHALL 接受副檔名為 `.json` 且檔案大小介於 1 至 1,048,576 bytes 的 Incident_Payload。
3. WHEN Incident_Payload 的頂層為非空陣列，THE Incident_Response_System SHALL 依陣列原始順序解析 Incident_Record。
4. WHEN Incident_Payload 的頂層為含非空 `incidents` 陣列的物件，THE Incident_Response_System SHALL 依 `incidents` 陣列原始順序解析 Incident_Record。
5. IF Incident_Payload 的頂層不是允許的兩種形式，THEN THE Incident_Response_System SHALL 拒絕整批注入並回傳頂層結構錯誤。
6. IF Incident_Payload 包含空事件陣列，THEN THE Incident_Response_System SHALL 拒絕整批注入並回傳至少需要一筆事件。
7. IF Incident_Payload 超過 100 筆 Incident_Record，THEN THE Incident_Response_System SHALL 拒絕整批注入並回傳 100 筆上限。
8. WHEN 管理員選擇 Scenario_Preset 或有效 Incident_Payload，THE Incident_Response_UI SHALL 在注入前顯示事件數量、原始順序、Event_Category、位置、嚴重度、事件時間與可能適用的 SOP 條款。
9. IF 新選擇的檔案無法解析或驗證，THEN THE Incident_Response_UI SHALL 保留上一份有效預覽並另行顯示新檔錯誤。
10. WHEN 預覽所依據的 Scenario_Preset 版本或 Incident_Payload 內容發生變更，THE Incident_Response_UI SHALL 清除既有確認狀態。
11. IF 管理員尚未確認目前預覽內容，THEN THE Incident_Response_UI SHALL 將目前預覽保持在未注入狀態。

### Requirement 3：事件契約與驗證

**User Story:** 作為系統維運者，我想在處理前驗證事件內容，以便讓 Demo 結果可預測且可追蹤。

#### Acceptance Criteria

1. THE Incident_Response_System SHALL 要求 `event_id` 為去除首尾空白後長度 1 至 64 的字串。
2. THE Incident_Response_System SHALL 要求 `type` 為去除首尾空白後長度 1 至 64 的字串。
3. THE Incident_Response_System SHALL 要求 `location` 為去除首尾空白後長度 1 至 120 的字串。
4. THE Incident_Response_System SHALL 要求 `affected_segment` 為去除首尾空白後長度 1 至 64 的字串。
5. THE Incident_Response_System SHALL 要求 `description` 為去除首尾空白後長度 1 至 500 的字串。
6. THE Incident_Response_System SHALL 接受 `Critical`、`High` 與 `Medium` 三種 `severity` 字串值。
7. THE Incident_Response_System SHALL 要求 `timestamp` 為代表 UTC+8 真實曆法日期與時間的 `YYYY-MM-DD HH:MM` 字串。
8. WHEN `affected_segment` 以 `RD_` 開頭、`type` 不是 `Power_Failure` 且 `description` 不包含「號誌失效」或「故障」，THE Incident_Response_System SHALL 將 Incident_Record 分類為 Road_Disruption。
9. WHEN `affected_segment` 以 `BS_` 開頭，THE Incident_Response_System SHALL 將 Incident_Record 分類為 Crowd_Surge。
10. WHEN `type` 為 `Power_Failure` 或 `description` 包含「號誌失效」或「故障」，THE Incident_Response_System SHALL 將 Incident_Record 分類為 Signal_Failure。
11. WHEN Incident_Record 屬於 Road_Disruption，THE Incident_Response_System SHALL 要求 `affected_segment` 為 Road_Network 中存在的 `RD_` 路段。
12. WHEN Incident_Record 屬於 Road_Disruption，THE Incident_Response_System SHALL 要求 `status` 為 `Closed`、`Blocked` 或 `Restricted`。
13. WHEN Incident_Record 屬於 Crowd_Surge，THE Incident_Response_System SHALL 要求 `affected_segment` 為 Crowd_Snapshot 中存在的 `BS_` 站點。
14. WHEN Incident_Record 屬於 Signal_Failure，THE Incident_Response_System SHALL 要求 `affected_segment` 為 Road_Network 中存在的 `RD_` 路段。
15. WHEN Incident_Record 屬於 Crowd_Surge，THE Incident_Response_System SHALL 接受省略 `status` 或提供長度 1 至 64 的字串 `status`。
16. WHEN Incident_Record 屬於 Signal_Failure，THE Incident_Response_System SHALL 接受省略 `status` 或提供長度 1 至 64 的字串 `status`。
17. IF Incident_Record 同時符合多個 Event_Category，THEN THE Incident_Response_System SHALL 拒絕整批 Incident_Payload 並指出衝突欄位路徑。
18. IF Incident_Record 無法分類為單一 Event_Category，THEN THE Incident_Response_System SHALL 拒絕整批 Incident_Payload 並指出 `type` 與 `affected_segment` 欄位路徑。
19. IF 同一 Incident_Payload 內存在重複 `event_id`，THEN THE Incident_Response_System SHALL 拒絕整批注入並列出重複值。
20. IF 任一 Incident_Record 欄位型別、長度、列舉值、日期時間或跨欄位關係無效，THEN THE Incident_Response_System SHALL 拒絕整批 Incident_Payload 並回傳每個錯誤的陣列索引與欄位路徑。
21. IF Incident_Payload 無法解析為 JSON，THEN THE Incident_Response_System SHALL 回傳不含伺服器堆疊資訊的結構化錯誤。

### Requirement 4：事件受理、生命週期與 60 秒目標

**User Story:** 作為交控指揮官，我想看見事件處理進度與完成時間，以便確認系統符合即時應變要求。

#### Acceptance Criteria

1. WHEN 管理員確認有效的 Incident_Payload，THE Incident_Response_API SHALL 在收到確認後 1 秒內回傳唯一 Incident_Run 識別碼、`accepted` 狀態與受理時間。
2. THE Incident_Response_System SHALL 使用 `accepted`、`validating`、`assessing`、`planning`、`generating`、`completed`、`completed_with_fallback`、`completed_with_partial_failure` 或 `failed` 表示 Incident_Run 狀態。
3. THE Incident_Response_System SHALL 允許 `accepted` 轉移至 `validating` 或 `failed`。
4. THE Incident_Response_System SHALL 允許 `validating` 轉移至 `assessing` 或 `failed`。
5. THE Incident_Response_System SHALL 允許 `assessing` 轉移至 `planning`、`completed_with_partial_failure` 或 `failed`。
6. THE Incident_Response_System SHALL 允許 `planning` 轉移至 `generating`、`completed_with_fallback`、`completed_with_partial_failure` 或 `failed`。
7. THE Incident_Response_System SHALL 允許 `generating` 轉移至任一 Terminal_Status。
8. IF 狀態轉移不符合已定義的合法轉移，THEN THE Incident_Response_System SHALL 拒絕狀態轉移並記錄目前狀態與目標狀態。
9. WHEN Incident_Run 狀態可由 Incident_Response_API 查得，THE Incident_Response_UI SHALL 在該狀態可查得後 2 秒內顯示目前階段。
10. WHEN Incident_Run 被受理，THE Incident_Response_System SHALL 以受理時間作為端到端耗時起點。
11. IF Incident_Run 在受理後 55 秒仍未具備可終止結果，THEN THE Incident_Response_System SHALL 啟用 Fallback_Mode。
12. IF Incident_Run 在受理後 58 秒仍不是 Terminal_Status 且至少一筆 Incident_Record 已形成 Deterministic_Result，THEN THE Incident_Response_System SHALL 依成功數、失敗數與 Fallback_Mode 使用狀態形成對應 Terminal_Status 結果。
13. IF Incident_Run 在受理後 58 秒仍不是 Terminal_Status 且沒有 Incident_Record 形成 Deterministic_Result，THEN THE Incident_Response_System SHALL 將 Incident_Run 終止為 `failed`。
14. WHEN Incident_Run 進入 Terminal_Status，THE Incident_Response_UI SHALL 在受理後 60 秒內完成處置結果畫面更新。
15. WHEN Incident_Run 的全部 Incident_Record 形成 Required_Result且未使用 Fallback_Mode，THE Incident_Response_System SHALL 將 Incident_Run 終止為 `completed`。
16. WHEN Incident_Run 的全部 Incident_Record 形成 Required_Result且使用 Fallback_Mode，THE Incident_Response_System SHALL 將 Incident_Run 終止為 `completed_with_fallback`。
17. WHEN Incident_Run 至少一筆 Incident_Record 形成 Required_Result且至少一筆未形成，THE Incident_Response_System SHALL 將 Incident_Run 終止為 `completed_with_partial_failure` 並記錄 Fallback_Mode 使用狀態。
18. IF Incident_Run 沒有任何 Incident_Record 形成 Required_Result，THEN THE Incident_Response_System SHALL 將 Incident_Run 終止為 `failed`。
19. WHEN Incident_Run 進入 Terminal_Status，THE Incident_Response_System SHALL 記錄總耗時、各處理階段耗時、成功數、失敗數與逐事件結果。
20. WHILE Incident_Run 處於 Terminal_Status，THE Incident_Response_System SHALL 保持狀態、輸入快照與結果不可變。

### Requirement 5：模擬時間與資料快照一致性

**User Story:** 作為評審，我想知道每項判定使用哪個時間點的資料，以便驗證系統沒有混用事件時間之後的資訊。

#### Acceptance Criteria

1. THE Simulation_Clock SHALL 作為 Monitoring_Dashboard 與 Incident_Response_System 的目前模擬時間權威來源。
2. WHEN Incident_Record 由 Monitoring_Alert 升級建立，THE Incident_Response_System SHALL 將原始 Monitoring_Alert 的資料時間設為 Effective_Event_Time。
3. WHEN Incident_Record 由 Scenario_Preset 或 JSON 建立，THE Incident_Response_System SHALL 將有效 `timestamp` 設為 Effective_Event_Time。
4. WHEN Effective_Event_Time 晚於 Simulation_Clock，THE Incident_Response_UI SHALL 將預覽標示為未來情境並要求管理員確認以事件時間預演。
5. WHEN 管理員確認未來情境預演，THE Incident_Response_System SHALL 使用 Effective_Event_Time 評估 Incident_Record 且保持 Simulation_Clock 不變。
6. WHEN 資料來源存在等於 Effective_Event_Time 的 Complete_Time_Slice，THE Incident_Response_System SHALL 使用該 Complete_Time_Slice 建立 Data_Snapshot。
7. WHEN 資料來源沒有等於 Effective_Event_Time 的 Complete_Time_Slice，THE Incident_Response_System SHALL 使用早於 Effective_Event_Time 的最近 Complete_Time_Slice 建立 Data_Snapshot。
8. THE Incident_Response_System SHALL 從 Data_Snapshot 排除時間晚於 Effective_Event_Time 的來源紀錄。
9. THE Incident_Response_System SHALL 依來源契約檢查 Traffic_Snapshot、Crowd_Snapshot 與 Road_Network 的必要欄位、型別、識別碼唯一性及引用完整性。
10. IF 資料來源在 Effective_Event_Time 以前沒有 Complete_Time_Slice，THEN THE Incident_Response_System SHALL 將該來源標記為不可用並列出受影響的 SOP 判定、路徑或 ETE 計算。
11. WHEN Incident_Run 建立首份 Data_Snapshot，THE Incident_Response_System SHALL 將該 Incident_Run 使用的來源紀錄與資料版本固定至 Terminal_Status。
12. THE Incident_Response_System SHALL 在 Decision_Trace 顯示 Effective_Event_Time、Simulation_Clock 時間、每個 Data_Snapshot 的實際資料時間與來源可用狀態。
13. WHEN 未來情境預演使用晚於 Simulation_Clock 且不晚於 Effective_Event_Time 的資料，THE Incident_Response_UI SHALL 明確標示該資料為事件時間預演資料。

### Requirement 6：SOP 判定與程式運算邊界

**User Story:** 作為交通專業評審，我想確認關鍵決策來自 SOP 與可重現運算，以便排除模型幻覺。

#### Acceptance Criteria

1. THE Response_Engine SHALL 以版本化 Incident_Record、Data_Snapshot、Road_Network 與 SOP 作為 Deterministic_Result 的完整輸入。
2. WHEN 相同的完整輸入被重複評估，THE Response_Engine SHALL 產生逐欄位相同的 Deterministic_Result。
3. WHEN Road_Disruption 的 `status` 屬於 `{Closed, Blocked, Restricted}`、`severity` 屬於 `{High, Critical}` 且 `affected_segment` 以 `RD_` 開頭，THE Response_Engine SHALL 將 SOP 第 2 條標記為已觸發並保留三個比較值。
4. WHEN `BS_MRT_BL17` 的 Growth_Rate 大於 `0.30` 或 User_Count 大於 `25000`，THE Response_Engine SHALL 將 SOP 第 3 條標記為已觸發並保留站點、數值、運算子與門檻。
5. WHEN Incident_Record 的 `type` 為 `Power_Failure` 或 `description` 包含「號誌失效」或「故障」，THE Response_Engine SHALL 將 SOP 第 5 條標記為已觸發並保留符合的比較證據。
6. WHEN 任一適用基地台的 Roaming_User_Pct 大於或等於 `0.30`，THE Response_Engine SHALL 將 SOP 第 6 條標記為已觸發並保留站點、數值、運算子與門檻。
7. IF 適用 SOP 判定缺少必要 Incident_Record 欄位或 Data_Snapshot 值，THEN THE Response_Engine SHALL 將該條款標記為 `indeterminate` 並列出缺少的輸入。
8. WHEN Deterministic_Result 引用 SOP 條款，THE Response_Engine SHALL 同時提供 SOP 版本、觸發狀態、輸入值、比較運算子與門檻。
9. THE Response_Engine SHALL 以程式運算產生事件分類、SOP 判定、候選排序、路徑、排除理由、ETE、號誌建議與跨系統動作。
10. THE AI_Narrative SHALL 僅使用 Deterministic_Result 與所引用 SOP 條款中的事實、數值及方案。
11. IF AI_Narrative 與 Deterministic_Result 衝突，THEN THE Incident_Response_System SHALL 捨棄 AI_Narrative 並保持 Deterministic_Result 不變。

### Requirement 7：道路事件重規劃、排除理由與 ETE

**User Story:** 作為交控指揮官，我想看到可執行的主次疏散路徑與排除理由，以便快速核准處置方案。

#### Acceptance Criteria

1. WHEN Road_Disruption 觸發 SOP 第 2 條，THE Response_Engine SHALL 僅從事故路段 Road_Network 紀錄的單向 `alternatives` 清單依原始順序建立候選路段。
2. THE Response_Engine SHALL 將事故路段排除於主疏散路徑與次要路徑之外。
3. WHEN 候選路段的 Road_Network 紀錄存在，THE Response_Engine SHALL 以該紀錄的 `capacity_vph` 作為容量比較值。
4. WHEN 候選路段與事故路段任一方的 `intersections` 包含另一方道路名稱，THE Response_Engine SHALL 將兩路段標記為直接相交。
5. WHEN 事故位置可對應事故路段的有序 `intersections` 項目，THE Response_Engine SHALL 依 `flow_direction` 與該項目前後順序判定直接相交候選路段為上游或下游。
6. IF 事故位置或 `flow_direction` 無法支持上游與下游判定，THEN THE Response_Engine SHALL 將相關候選路段標記為方向不可判定。
7. WHEN 候選路段的 `capacity_vph` 大於或等於 `1000`、直接相交、位於上游且具有 Traffic_Snapshot 飽和度，THE Response_Engine SHALL 將該路段標記為主路徑合格候選。
8. WHEN 存在主路徑合格候選，THE Response_Engine SHALL 依飽和度由低至高及 `segment_id` 字典序的穩定排序選擇第一名為主疏散路徑。
9. WHEN 存在容量大於或等於 `1000`、直接相交、位於下游且具有 Traffic_Snapshot 飽和度的候選路段，THE Response_Engine SHALL 依相同穩定排序列為次要路徑。
10. IF 所有主路徑合格候選的飽和度均大於或等於 `0.85`，THEN THE Response_Engine SHALL 保留排序第一名為主疏散路徑並標記壅塞例外。
11. WHEN 主疏散路徑被標記為壅塞例外，THE Response_Engine SHALL 產生長綠燈時制與併行大眾運輸建議。
12. IF 不存在主路徑合格候選，THEN THE Response_Engine SHALL 將道路重規劃標記為不可規劃並列出容量不足、不相交、下游、方向不可判定或缺少飽和度的排除理由。
13. THE Decision_Trace SHALL 列出每個候選路段的來源順序、容量、相交關係、上下游關係、飽和度、排序鍵、選取狀態與排除理由。
14. WHEN Incident_Record 的受影響 `RD_` 路段具有有效飽和度與有效 `severity`，THE Response_Engine SHALL 依 `base_clearance + max(0, (受影響路段飽和度算術平均 - 0.5) × 60)` 計算 ETE 分鐘數。
15. WHEN Response_Engine 計算 ETE，THE Response_Engine SHALL 使用 `Critical=60`、`High=40`、`Medium=20` 分鐘作為 `base_clearance`。
16. WHEN ETE 完成計算，THE Decision_Trace SHALL 顯示參與平均的路段與飽和度、算術平均、`base_clearance`、壅塞加成及總分鐘數。
17. IF 受影響道路飽和度或嚴重度基礎時間不可取得，THEN THE Response_Engine SHALL 將 ETE 標記為不可計算並列出缺少的輸入。

### Requirement 8：三類事件的差異化處置

**User Story:** 作為 Demo 操作者，我想讓三類事件呈現不同且符合 SOP 的成果，以便展示系統不是套用單一模板。

#### Acceptance Criteria

1. WHEN Road_Disruption 完成處理，THE Incident_Response_UI SHALL 顯示 SOP 第 2 條判定、主疏散路徑、次要路徑、號誌建議、ETE 與道路 CMS_Message。
2. IF Road_Disruption 沒有合格次要路徑，THEN THE Incident_Response_UI SHALL 顯示「無合格次要路徑」及排除理由。
3. WHEN Crowd_Surge 觸發 SOP 第 3 條，THE Response_Engine SHALL 產生北捷過站不停、公車接駁與步行至 `BS_MRT_BL18` 的模擬跨系統建議。
4. WHEN Crowd_Surge 完成處理，THE Incident_Response_UI SHALL 顯示站點、人流數值、觸發門檻、分流目的地、SOP 判定與跨系統建議。
5. IF Crowd_Surge 未觸發 SOP 第 3 條，THEN THE Response_Engine SHALL 將北捷過站不停、公車接駁與步行至 `BS_MRT_BL18` 標記為未建議。
6. WHEN Signal_Failure 完成處理，THE Response_Engine SHALL 以受影響道路集合中不重複的 `intersections` 數量乘以 2 計算建議警力人數。
7. WHEN Signal_Failure 完成處理，THE Incident_Response_UI SHALL 顯示 SOP 第 5 條判定、受影響路段、不重複受影響路口、建議警力、以 ETE 表示的估計持續時間或不可計算原因，以及號誌故障 CMS_Message。
8. IF Crowd_Surge 缺少有效道路影響範圍或 Signal_Failure 缺少有效道路 Data_Snapshot，THEN THE Response_Engine SHALL 將道路 ETE 標記為不可計算並說明原因。
9. WHEN 處置結果包含北捷、公車、警力、CMS、簡訊或號誌動作，THE Incident_Response_UI SHALL 將每項動作標示為模擬建議或 Simulated_Publish。
10. WHEN Incident_Record 形成結果，THE Incident_Response_UI SHALL 使用符合 Event_Category 的結果標題與完成訊息。

### Requirement 9：AI 價值、可解釋性與降級

**User Story:** 作為評審，我想看見 AI 如何提升資訊整合與溝通，同時保留可驗證的計算證據，以便評估 AI 使用是否合理。

#### Acceptance Criteria

1. THE AI_Narrative SHALL 使用繁體中文並限制於 500 個 Unicode 字元以內。
2. THE AI_Narrative SHALL 包含事件類別、位置、Effective_Event_Time、SOP 判定與比較證據、主要處置、ETE 或不可計算原因，以及模擬跨系統動作。
3. THE Incident_Response_System SHALL 逐項比對 AI_Narrative 中的 SOP 編號、識別碼、數值、時間、路徑與動作是否存在於 Deterministic_Result。
4. WHEN AI_Narrative 通過一致性檢查，THE Incident_Response_UI SHALL 標示內容為 `AI 生成說明`。
5. IF AI_Narrative 未通過一致性檢查，THEN THE Incident_Response_System SHALL 捨棄 AI_Narrative 並啟用 Fallback_Mode。
6. IF 生成式 AI 服務自請求開始 15 秒內未回傳有效 AI_Narrative，THEN THE Incident_Response_System SHALL 取消等待並啟用 Fallback_Mode。
7. IF 生成式 AI 服務拒絕請求或回傳錯誤，THEN THE Incident_Response_System SHALL 隱藏供應商原始錯誤並啟用 Fallback_Mode。
8. WHEN Fallback_Mode 被啟用，THE Incident_Response_System SHALL 記錄 `timeout`、`service_error`、`consistency_failure` 或 `global_deadline` 的備援原因代碼。
9. WHEN Fallback_Mode 被啟用，THE Incident_Response_UI SHALL 標示內容為 `SOP 備援說明` 並顯示可讀的備援原因。
10. IF 有效 AI_Narrative 在 Fallback_Mode 結果形成後才抵達，THEN THE Incident_Response_System SHALL 保持既有結果與 Terminal_Status 不變。
11. THE Decision_Trace SHALL 僅呈現結構化輸入、規則、比較、候選、排除理由與結果。
12. THE Incident_Response_UI SHALL 分開呈現 Deterministic_Result、Decision_Trace 與 AI_Narrative 或 SOP 備援說明。

### Requirement 10：處置畫面、歷程與重播

**User Story:** 作為交控指揮官，我想在單一戰情畫面查看事件、方案與處理歷程，以便快速理解並比較多筆事件。

#### Acceptance Criteria

1. WHEN Incident_Run 被受理，THE Incident_Response_UI SHALL 顯示事件摘要、Source_Label、目前階段、完成事件數、總事件數與已耗時間。
2. WHEN Incident_Run 產生多筆事件結果，THE Incident_Response_UI SHALL 允許管理員依 Incident_Payload 原始順序切換同批事件。
3. WHEN 事件的 `location` 或 `affected_segment` 可對應 Road_Network 或站點座標，THE Incident_Response_UI SHALL 在地圖或降級路網視圖標示事件位置。
4. IF 事件無法對應可用座標，THEN THE Incident_Response_UI SHALL 顯示不可定位原因並保留文字結果。
5. WHEN Road_Disruption 具有路徑結果，THE Incident_Response_UI SHALL 以不同視覺樣式標示事故路段、主疏散路徑與次要路徑。
6. THE Incident_Response_UI SHALL 顯示事故、主路徑、次要路徑、壅塞例外、站點與不可用資料的視覺圖例。
7. THE Incident_Response_System SHALL 在 Demo_Session 內依受理時間由新至舊保留最近 100 個 Incident_Run。
8. WHEN 第 101 個 Incident_Run 被受理，THE Incident_Response_System SHALL 從 Demo_Session 歷程移除受理時間最早的 Incident_Run。
9. WHEN 管理員選擇歷史 Incident_Run，THE Incident_Response_UI SHALL 以唯讀方式還原該執行固定的輸入摘要、Data_Snapshot 時間、Decision_Trace、建議書、通報與發布狀態。
10. IF 歷史 Incident_Run 缺少當時的地圖或來源資料，THEN THE Incident_Response_UI SHALL 顯示歷史資料不可用且不以目前資料替代。
11. WHEN 管理員重播歷史 Incident_Run，THE Incident_Response_System SHALL 建立具有新識別碼的新 Incident_Run 並引用原始 Incident_Run 識別碼。
12. IF 外部地圖底圖無法載入，THEN THE Incident_Response_UI SHALL 顯示可讀的本地降級路網、事件標記、路徑樣式與文字結果。
13. WHILE 任一 Incident_Run 處於非 Terminal_Status，THE Incident_Response_UI SHALL 將 Demo 重設操作保持為不可執行狀態。
14. WHEN 管理員在沒有執行中 Incident_Run 時確認 Demo 重設，THE Incident_Response_System SHALL 清除 Demo_Session 歷程並將 Simulation_Clock 回到起始時間。

### Requirement 11：公眾通報與展示發布

**User Story:** 作為交控指揮官，我想取得適合公眾閱讀的多語訊息並模擬發布，以便展示跨通路協調價值。

#### Acceptance Criteria

1. WHEN 事件涉及 Road_Network 的 `nearby_stations`，THE Response_Engine SHALL 檢查該清單中每一個站點於固定 Crowd_Snapshot 的 Roaming_User_Pct。
2. WHEN 任一適用站點的 Roaming_User_Pct 大於或等於 `0.30`，THE Response_Engine SHALL 產生繁體中文、英文、日文與韓文 CMS_Message。
3. WHEN 所有適用站點皆具有 Roaming_User_Pct 且每個值均小於 `0.30`，THE Response_Engine SHALL 產生繁體中文 CMS_Message。
4. IF 沒有可用適用站點達到 `0.30` 且任一適用站點缺少 Roaming_User_Pct，THEN THE Response_Engine SHALL 將 SOP 第 6 條標記為 `indeterminate` 並列出缺少資料的站點。
5. THE CMS_Message SHALL 包含適用的事件位置、避開或改道指引，以及 ETE、估計延誤或不可計算說明。
6. THE CMS_Message SHALL 將每一語言版本限制於 160 個 Unicode 字元以內。
7. THE Incident_Response_System SHALL 驗證各語言 CMS_Message 的事件位置、路徑、時間數值與動作語意和 Deterministic_Result 一致。
8. IF 任一語言 CMS_Message 未通過事實一致性檢查，THEN THE Incident_Response_System SHALL 將整組 CMS_Message 標記為不可發布並列出失敗語言。
9. WHEN 管理員執行發布操作，THE Incident_Response_UI SHALL 在確認畫面與完成畫面標示 `Simulated_Publish－未連接真實通路`。
10. WHEN Simulated_Publish 成功，THE Incident_Response_System SHALL 以單一原子操作記錄全部選定語言的 Incident_Run、語言、訊息內容與 UTC+8 發布時間。
11. IF Simulated_Publish 的任一選定語言無法記錄，THEN THE Incident_Response_System SHALL 保持該次發布的所有選定語言均為未發布。
12. THE CMS_Message SHALL 使用公眾可讀文字取代程式欄位名稱、內部錯誤資訊與供應商資訊。

### Requirement 12：API 契約、冪等與錯誤回應

**User Story:** 作為前端開發者，我想使用一致且可追蹤的 API 契約，以便可靠呈現處理進度與部分失敗。

#### Acceptance Criteria

1. THE Incident_Response_API SHALL 讓 JSON 直接注入與 `.json` 檔案上傳共用 Requirement 2 與 Requirement 3 的解析及驗證規則。
2. THE Incident_Response_API SHALL 使用契約版本 `1.0` 回傳受理、查詢、結果與錯誤回應。
3. WHEN Incident_Payload 成功受理，THE Incident_Response_API SHALL 回傳契約版本、Incident_Run 識別碼、狀態、Source_Label、受理時間、事件數量與查詢位置。
4. THE Incident_Response_API SHALL 提供依 Incident_Run 識別碼查詢目前狀態、進度、逐事件結果與 Terminal_Status 結果的能力。
5. WHEN 相同 Idempotency_Key、契約版本與正規化 Incident_Payload 被重送，THE Incident_Response_API SHALL 回傳首次受理的 Incident_Run 且不建立新執行。
6. IF 相同 Idempotency_Key 與契約版本被用於不同的正規化 Incident_Payload，THEN THE Incident_Response_API SHALL 回傳 `409` 衝突與原 Incident_Run 識別碼。
7. IF 請求內容、檔案或查詢參數驗證失敗，THEN THE Incident_Response_API SHALL 回傳適用的 4xx 狀態、穩定錯誤代碼、欄位路徑與可讀訊息。
8. IF 伺服器無法建立或查詢 Incident_Run，THEN THE Incident_Response_API SHALL 回傳適用的 5xx 狀態與不含堆疊、憑證、內部路徑或供應商內容的追蹤識別碼。
9. WHEN Incident_Run 含部分失敗，THE Incident_Response_API SHALL 回傳 `completed_with_partial_failure`、成功數、失敗數、Fallback_Mode 使用狀態與逐事件結果。
10. THE Incident_Response_API SHALL 將所有輸出時間轉換為 UTC+8 並格式化為 `YYYY-MM-DD HH:MM`。
11. THE Incident_Response_API SHALL 在契約中以 `UTC+08:00` 明示所有無偏移量輸出時間的時區。

### Requirement 13：未來模組一模擬時間整合

**User Story:** 作為 Demo 操作者，我想由後端控制一天的模擬時間，以便自然展示自動預警後再注入突發事件的完整故事線。

#### Acceptance Criteria

1. THE Simulation_Clock SHALL 只使用 Traffic_Snapshot 與 Crowd_Snapshot 在相同時間各自具有 Complete_Time_Slice 的共同時間切片。
2. THE Simulation_Clock SHALL 依共同時間切片由最早時間推進至最晚時間。
3. THE Simulation_Clock SHALL 提供播放、暫停、重設與目前模擬時間。
4. WHILE Simulation_Clock 處於播放狀態且沒有非 Terminal_Status 的 Incident_Run，THE Simulation_Clock SHALL 每一個實際秒前進一個共同時間切片。
5. WHEN Simulation_Clock 推進到新的共同時間切片，THE Monitoring_Dashboard SHALL 更新 Traffic_Snapshot 與 Crowd_Snapshot。
6. WHEN 同一路段目前 Saturation_Score 由前一個 Data_Snapshot 的 `<0.85` 跨越至 `>=0.85`，THE Monitoring_Dashboard SHALL 產生一次 B 級 Monitoring_Alert。
7. WHEN 同一路段目前 Saturation_Score 由前一個 Data_Snapshot 的 `<0.95` 跨越至 `>=0.95`，THE Monitoring_Dashboard SHALL 產生一次 A 級 Monitoring_Alert。
8. WHILE 同一路段 Saturation_Score 未降回 B 級門檻以下，THE Monitoring_Dashboard SHALL 保持該路段 B 級門檻為未重新武裝狀態。
9. WHILE 同一路段 Saturation_Score 未降回 A 級門檻以下，THE Monitoring_Dashboard SHALL 保持該路段 A 級門檻為未重新武裝狀態。
10. WHEN 同一路段 Saturation_Score 降回特定門檻以下，THE Monitoring_Dashboard SHALL 重新武裝該路段的該門檻。
11. WHEN 已重新武裝的路段再次跨越特定門檻，THE Monitoring_Dashboard SHALL 建立新的對應 Monitoring_Alert。
12. WHEN 管理員從 Monitoring_Alert 進入模組二，THE Incident_Response_UI SHALL 預填原始資料時間、受影響路段、前後 Saturation_Score、門檻級別與 Monitoring_Alert 識別碼。
13. WHILE 任一 Incident_Run 處於非 Terminal_Status，THE Simulation_Clock SHALL 依 Requirement 1 保持時間與步進凍結。
14. WHILE 管理員檢視已完成 Incident_Run，THE Monitoring_Dashboard SHALL 保留 Incident_Run、原始 Monitoring_Alert 與原始共同時間切片的關聯。

### Requirement 14：競賽 Demo 可驗收結果

**User Story:** 作為參賽團隊，我想用穩定且可重現的流程展示 AI Agent 價值，以便評審在短時間內驗收核心能力。

#### Acceptance Criteria

1. WHEN Demo_Session 完成重設，THE Incident_Response_UI SHALL 在選擇教案與開啟預覽兩次操作內顯示任一 Scenario_Preset 的預覽。
2. WHEN Road_Disruption Scenario_Preset 被受理，THE Incident_Response_UI SHALL 在 60 秒內顯示 SOP 第 2 條判定、主次路徑或無合格路徑、排除理由、號誌建議、ETE 或不可計算原因、CMS_Message 與端到端耗時。
3. WHEN Crowd_Surge Scenario_Preset 被受理，THE Incident_Response_UI SHALL 在 60 秒內顯示 SOP 第 3 條判定、人流證據、接駁分流或未觸發說明、模擬跨系統請求、CMS_Message 與端到端耗時。
4. WHEN Signal_Failure Scenario_Preset 被受理，THE Incident_Response_UI SHALL 在 60 秒內顯示 SOP 第 5 條判定、不重複受影響路口、警力估算、估計持續時間或不可計算原因、故障 CMS_Message 與端到端耗時。
5. IF 生成式 AI 服務在 Demo 期間不可用，THEN THE Incident_Response_System SHALL 以 Fallback_Mode 在相同 60 秒上限內形成三個 Scenario_Preset 的 Terminal_Status 結果。
6. IF 公網在 Demo 期間不可用，THEN THE Incident_Response_UI SHALL 保留教案注入、Decision_Trace、處置結果、本地降級路網與 Simulated_Publish 紀錄能力。
7. WHEN 相同 Scenario_Preset 版本、資料版本、SOP 版本與 Effective_Event_Time 被重播，THE Incident_Response_System SHALL 產生逐欄位相同的 Deterministic_Result。
8. THE Incident_Response_System SHALL 以不同 Incident_Run 分別保存三個 Scenario_Preset 的輸入、Data_Snapshot、結果、通報與發布狀態。
9. IF Scenario_Preset 在 60 秒內缺少任一 Required_Result，THEN THE Incident_Response_System SHALL 將該 Incident_Run 終止為 `failed` 並列出缺少項目。
10. WHEN 管理員在沒有執行中 Incident_Run 時確認 Demo 重設，THE Incident_Response_System SHALL 清除 Demo_Session 的 Incident_Run、預覽、確認、通報、發布與門檻重新武裝狀態。

## 非目標與範圍限制

1. 本 POC 不直接控制真實號誌、警力派遣、北捷、公車、CMS 或電信簡訊系統。
2. 本 POC 不宣稱取代交控人員的核准責任。
3. 本階段不要求跨 Demo_Session 的永久稽核保存；若後續需要正式上線，應另訂保存年限、權限與個資要求。
4. 本階段不擴充模組三 What-if 功能，但 Incident_Run 的資料契約應可供模組三引用。
5. 本階段不要求以模型生成數值、路徑或 SOP 觸發判定。

## 需求追溯至核心目標

| 核心目標 | 對應內容 |
|---|---|
| 模組一與模組二關聯、責任與資料流 | 邊界分析、Requirement 1、5、13 |
| 自動預警與 JSON 注入差異 | 差異分析、Requirement 1、6 |
| 現有前後端、JSON、API、流程調整 | 現況檢視、Requirement 2、3、4、10、12 |
| 未來後端模擬時間整合 | Requirement 5、13 |
| Demo／POC 定位與可驗收結果 | Requirement 8、9、10、11、14 |
| 後續設計與實作步驟 | 下節規劃 |

## 後續設計與實作規劃（本階段不執行）

### Design 階段

1. 定義版本化 Incident_Payload、Incident_Run、Decision_Trace 與錯誤回應資料模型。
2. 設計 Simulation_Clock 與各資料來源的 as-of Data_Snapshot 取樣規則。
3. 設計 Response_Engine 的事件分類、SOP 規則、路徑候選、ETE、通報與 AI 降級邊界。
4. 設計非同步受理、狀態查詢、60 秒截止與冪等流程。
5. 設計三個 Scenario_Preset 與預期 Deterministic_Result 黃金資料。
6. 設計 Incident_Response_UI 的預覽、確認、進度、地圖、Decision_Trace、歷程、重播及 Simulated_Publish 流程。
7. 設計無 Bedrock、無公網與部分資料缺漏時的降級體驗。
8. 定義安全性、檔案大小、輸入清理、日誌遮罩與可觀測性。

### Tasks／Implementation 階段建議順序

1. 先建立資料契約、驗證器與三個教案 fixture。
2. 再建立 Simulation_Clock 與一致 Data_Snapshot 服務。
3. 將現有規則與交通計算重構為可重現的 Response_Engine，補齊候選排除證據。
4. 建立 Incident_Run 生命週期、冪等、計時及 Fallback_Mode。
5. 統一 `/api/incidents` 與 `/api/incidents/upload` 的受理與錯誤契約。
6. 改造事件 UI 為預覽、確認、進度、差異化結果與歷程流程。
7. 擴充地圖／降級路網視圖與 Simulated_Publish 稽核。
8. 最後整合模組一 Simulation_Clock、自動預警及明確升級入口。
9. 以單元測試驗證 SOP、路徑與 ETE，以契約測試驗證 API，以整合測試驗證三類教案，以端到端測試驗證 60 秒與降級 Demo。
