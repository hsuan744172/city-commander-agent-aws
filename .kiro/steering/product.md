# 城市應變指揮官 (City Commander Agent) — 全局產品指引 v2.1

## 核心目標

打造具備「主動感知、極速決策、跨域協調」的 AI 交通指揮中心。

1. **即時事件偵測與分級** — 自動判定交通癱瘓等級（A / B 級）
2. **法規 SOP 比對與觸發** — 自動識別應觸發之 SOP 條款（第 1～7 條全部）
   - 事件型：第 2、5 條
   - 資料型（不需事件注入，儀表板主動偵測）：第 3、4、6 條
3. **替代路徑計算與 ETE 估算** — 篩選主疏散路段、輸出排除理由並計算預估恢復時間
4. **多語系公眾通報** — 繁中/英/日/韓四語 CMS 看板文字與民眾簡訊
5. **主動預警** — 達門檻自動彈窗，門檻判定由程式運算、摘要由 LLM 生成
6. **What-if 顧問** — 可呼叫計算工具、保留對話記憶、附上引用條文原文

最終產出：「交控中心建議書」JSON，透過 Dashboard 即時呈現。

架構圖與職責邊界見 `docs/architecture.md`。

---

## 技術架構 (v2.1)

```text
Frontend (React 19 + Vite 6 + Tailwind CSS 4)
       │ HTTP / WebSocket，同源存取
       ▼
Application Load Balancer
       │ 健康檢查：GET /api/health
       ▼
Amazon ECS Fargate
  └── 單一正式 Docker 映像
      ├── FastAPI + Python 3.13
      │   ├── GET  /api/status           → 路網狀態、自動應變、資料型 SOP、門檻表
      │   ├── GET  /api/alert-summary    → LLM 預警摘要（門檻仍由程式判定）
      │   ├── GET  /api/sop              → SOP 條文原文
      │   ├── GET  /api/trend            → 路網趨勢
      │   ├── GET/POST /api/clock*       → 模擬時鐘（前端時間軸控制列）
      │   ├── POST /api/incidents        → Architect Agent
      │   ├── POST /api/incidents/preview|inject → 三段式事件注入（契約層驗證）
      │   ├── POST /api/what-if          → What-if 問答（工具呼叫 + 對話記憶）
      │   └── WS   /ws/dashboard         → 狀態推播 + 注入後建議書廣播
      ├── React Dashboard 編譯產物
      └── Strands Agents SDK
          ├── sop_rules（門檻／分類／上下游，無 I/O）
          ├── traffic_math（唯一數值計算）
          ├── Policy Agent（SOP 1~7 判定，條文原文擷取）
          ├── Router Agent（路徑 + ETE + 號誌配時）
          ├── Comms Agent（四語 CMS 與民眾簡訊）
          ├── advisor_tools（What-if 顧問的 9 個計算工具）
          └── Amazon Bedrock Claude Sonnet 4.6

映像流程：Docker Buildx → Amazon ECR → ECS Fargate
公開入口：Application Load Balancer → Fargate 任務連接埠 8080
```

### AWS 部署原則

- 目前正式可用部署路徑為 `scripts/deploy-ecs-fargate.sh`。
- 正式映像由 `backend/Dockerfile` 多階段建置：先編譯 React，再由 FastAPI 同源提供前端與 API。
- ECS 任務以專用角色呼叫 Bedrock，不得向容器注入長期 AWS 金鑰。
- Bedrock 預設模型為 `us.anthropic.claude-sonnet-4-6`。
- ALB 使用 `/api/health` 判定任務健康狀態。
- 目前 ALB 為 HTTP；正式公開上線前應加入自有網域、ACM 憑證及 HTTPS Listener。

---

## 資料環境

| 資料檔案 | 用途 |
|----------|------|
| `data/city_traffic_flow.csv` | 即時路段飽和度 |
| `data/road_network_geometry.json` | 路網拓樸 |
| `data/signaling_crowd_density.csv` | 捷運站人流密度 |
| `data/emergency_traffic_sop.txt` | 官方交通應變 SOP |

---

## 全局邊界約束

### 約束 1：嚴禁數學幻覺

所有數值計算（飽和度比對、ETE、路徑篩選、漫遊掃描、號誌配時）只在
`backend/agents/traffic_math.py` 執行。Agent 僅負責組裝參數與解讀回傳值。

### 約束 1b：規則常數單一來源

SOP 的門檻、觸發路段、事件分類與上下游判定只在 `backend/agents/sop_rules.py` 定義。
`policy.py`、`main.py` 與前端都不得自行寫死 0.85 / 0.95 / 30% 等數值；
前端由 `GET /api/status` 的 `thresholds` 取得。

### 約束 2：時間格式統一

所有對外輸出時間欄位一律 **`YYYY-MM-DD HH:MM`**。

### 約束 3：公眾訊息範本

- 一般事故：`「<事故路段>封閉，請改道 <主疏散路段>，預計延誤 <ETE> 分鐘」`
- 號誌故障：`「<路段> 號誌故障，請依現場指揮通行」`

### 約束 4：多語系觸發

SOP 第 6 條原文為「**任一**基地台 Roaming_User_Pct >= 30%」。判定範圍是**全資料集所有基地台**，
不是事故路段的 `nearby_stations`。唯一判定入口是 `traffic_math.scan_roaming()`。
觸發 → 繁中/英/日/韓四語；未觸發 → 僅繁中。
漫遊率一律以 0~1 表示，顯示字串另外提供，禁止 0~100 與 0~1 兩套單位並存。

### 約束 5：路段篩選邏輯

1. `capacity_vph` >= 1000
2. 與事故路段直接相交（名稱出現在其 `intersections`）
3. 相交路口位於事故點上游 — 由 `sop_rules.resolve_upstream()` 依事故位置描述與
   `flow_direction` 判定；無法定位時退回「陣列前半」啟發式並在報告標明判定方法
4. 通過篩選者取 Saturation_Score 最低者為主疏散；位於下游之相交幹道僅列次要疏散

主疏散不得同時出現在次要疏散清單。每個 alternative 都必須出現在候選表並附上
選用或排除理由（對應交付要求「說明排除其他候選之理由」）。

### 約束 5b：SOP 第 1 條應變僅限觸發路段

「城市應變觸發路段」只有 `RD_TPE_001`（忠孝東路四段）與 `RD_TPE_002`（光復南路）。
其餘 13 段的分級僅用於 Dashboard 紅黃燈顯示，不得啟動長綠燈時制或替代路徑引導，
應列入 `monitored_alerts`。

觸發路段達 B 級：替代道路（`alternatives` 全集）綠燈 +25% ＋ 調度警力淨空路口。
達 A 級：另加第 2 條替代路徑引導。

### 約束 6：ETE 公式與受影響路段定義

```text
ETE_minutes = base_clearance + congestion_penalty
  Critical → 60, High → 40, Medium → 20
  congestion_penalty = max(0, (avg_saturation - 0.5) × 60)
```

「受影響路段」的定義只有一處：`traffic_math.affected_segments_for_ete()`
= 事故路段 + 主疏散路段 + 次要疏散路段。儀表板自動應變與事件建議書必須共用它，
同一路段不得算出兩個 ETE。

查無車流量測時**不得**代入預設飽和度：壅塞懲罰以 0 計，並在
`saturation_data_available` 與 `note` 明確標示。

儀表板對純壅塞（無事故通報）的自動應變需要一個嚴重度，依分級換算
（A 級視同 Critical、B 級視同 High），並在 `severity_basis` 標明這是換算假設。

### 約束 6b：人流 ↔ 車流融合

`live_incidents.json` 的人流事件（`BS_` 開頭）可帶 `affected_road` 指出連帶受影響的
車流路段。`sop_rules.classify_incident()` 會據此解析 `traffic_segment`，交通分級與 ETE
都用該路段計算。任何事件模型（含 `main.Incident`）都必須保留 `affected_road` 欄位。

### 約束 7：AI 輸出格式規範

- **嚴格禁止**輸出任何 LaTeX 數學符號（$...$、\frac 等）
- **嚴格禁止**輸出程式碼變數名稱（Saturation_Score、capacity_vph 等）
- **嚴格禁止**使用 Markdown 程式碼區塊於對外回應中
- 所有數值以中文自然語言表述（如「飽和度 95%」）
- AI 回覆必須以交控中心長官口吻，簡潔果斷，字數控制在 500 字以內

### 約束 8：資料依據唯一來源

所有決策與數值計算**必須嚴格依據**專案根目錄下的：
- `data/emergency_traffic_sop.txt`（應變程序原文）
- `data/road_network_geometry.json`（路網拓樸）
- `data/city_traffic_flow.csv`（即時飽和度）
- `data/signaling_crowd_density.csv`（人流密度）

禁止使用未經上述文件證實的假設性數字。

### 約束 9：Fallback 機制（路徑篩選）

當 SOP 第 2 條嚴格篩選無完全符合者時，依序退階：
1. 取下游相交路段中飽和度最低者
2. 取所有替代路段中容量 >= 1000 且飽和度最低者
3. 絕不回傳空值，至少提供一條建議路段並標註「Fallback」

### 約束 10：雲端憑證與權限

- 禁止將 AWS access key、secret key 或 session token 寫入 `.env`、原始碼、Docker image 或版本控制。
- 本機使用 AWS CLI profile、SSO 或臨時角色；ECS 使用 Task Role。
- Bedrock Task Role 僅授權實際使用的模型與必要推論動作。

---

## 開發與部署指令

```bash
# 初始化本機環境
cp .env.example .env
uv sync --all-groups

# 本機後端
uv run uvicorn backend.main:app --reload --port 8000

# 本機前端（另一終端機）
cd frontend && npm ci && npm run dev

# Docker 全端
docker compose up --build

# 正式 AWS 部署：ECR + ECS Fargate + ALB
AWS_PROFILE=city-commander-deploy AWS_REGION=us-west-2 \
  bash scripts/deploy-ecs-fargate.sh

# 驗證
uv run pytest -q
uv run python -m py_compile backend/main.py backend/agents/*.py
cd frontend && npm run build
bash -n scripts/deploy-ecs-fargate.sh
```

部署完成後，必須驗證 Dashboard、`/api/health`、`/api/status`、`/docs`、`/api/what-if` 與 `/api/incidents`。AI 驗證須確認模型回覆無 Bedrock 錯誤、使用資料時間、字數不超過 500 字且未引用資料來源外數值。

---

## 專案結構

```text
city-commander-agent/
├── backend/
│   ├── main.py                  # FastAPI 入口、API、WebSocket、前端靜態服務
│   ├── agents/
│   │   ├── sop_rules.py         # SOP 門檻／事件分類／上下游判定（規則單一來源）
│   │   ├── traffic_math.py      # 唯一數學計算模組
│   │   ├── policy.py            # 法規驗證與條文原文擷取
│   │   ├── router.py            # 路網 Agent
│   │   ├── comms.py             # 多語通報 Agent
│   │   ├── advisor_tools.py     # What-if 顧問工具
│   │   └── architect.py         # 總指揮、預警摘要、What-if
│   └── Dockerfile               # React + FastAPI 正式單一映像
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   └── components/
│   ├── package.json
│   ├── package-lock.json
│   ├── Dockerfile               # 本機 Compose 前端映像
│   └── nginx.conf
├── data/                        # SOP、路網、流量與人流資料
├── deployment/iam/              # 服務信任與 Bedrock IAM policies
├── scripts/
│   └── deploy-ecs-fargate.sh    # 正式 AWS 部署腳本
├── docker-compose.yml
├── pyproject.toml
├── uv.lock
└── .env.example
```
