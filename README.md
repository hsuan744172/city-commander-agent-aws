# 城市應變指揮官 (City Commander Agent)

AI 驅動的智慧交通應變指揮系統，提供即時感知、決策支援、替代路徑規劃與多語公眾通報。

## 技術架構

| 層級 | 技術 |
|---|---|
| Frontend | React 19、Vite 6、Tailwind CSS 4 |
| Backend | FastAPI、Python 3.13 |
| AI | Strands Agents SDK、Amazon Bedrock Claude Sonnet 4.6 |
| Python 管理 | uv、`uv.lock` |
| 容器 | Docker，多階段建置的單一全端映像 |
| AWS | Amazon ECR、Amazon ECS Fargate、Application Load Balancer |

正式環境只部署一個容器映像：建置階段先編譯 React Dashboard，執行階段由 FastAPI 同源提供前端、API 與 WebSocket。映像推送至 ECR，再由 ECS Fargate 執行，ALB 負責公開入口與健康檢查。

```text
Client
  │ HTTP / WebSocket
  ▼
Application Load Balancer
  │ /api/health 健康檢查
  ▼
ECS Fargate
  └── 單一 Docker image
      ├── React Dashboard
      ├── FastAPI API / WebSocket
      └── Strands Agents SDK
              │
              ▼
      Amazon Bedrock Claude Sonnet 4.6
```

## 功能模組

1. **動態路網監測**：依模擬時鐘呈現路段飽和度、速度、車流與 A/B 級分級；儀表板另有
   時間軸控制列可暫停、回放與跳至指定時間點。
2. **主動預警**：達 SOP 門檻時在儀表板左上角顯示不遮蔽畫面的預警 toast（可展開判定明細，
   靜置後自動收起）。門檻判定由程式運算，摘要由 LLM 生成
   （`GET /api/alert-summary`）。人流與信令的 SOP 第 3、4、6 條**不需要事件注入**即會主動偵測。
3. **突發事件應變**：三段式注入（目錄 → 預覽 → 確認），產出「交控中心建議書」並回報端到端耗時。
4. **AI 策略對話**：What-if 顧問可呼叫路網計算工具取得確定性結果，保留對話記憶，
   並附上實際引用的 SOP 條文原文。
5. **替代路徑與 ETE**：由 `traffic_math` 執行路徑篩選與恢復時間估算，輸出每個候選替代道路
   被選用或排除的理由。
6. **多語公眾通報**：全市任一基地台漫遊率達 30% 觸發 SOP 第 6 條，產生繁中、英、日、韓的
   CMS 看板文字與民眾簡訊。

### SOP 條款實作對照

| 條款 | 觸發來源 | 實作位置 |
|---|---|---|
| 1 交通擁塞級別 | 車流飽和度 | `sop_rules.assess_congestion_level`；應變限於觸發路段 `RD_TPE_001`、`RD_TPE_002` |
| 2 車禍與路障 | 事件 | `policy.check_sop2_trigger` + `traffic_math.calculate_optimal_route` |
| 3 捷運與接駁分流 | **資料** | `policy.check_sop3_trigger`（儀表板主動偵測） |
| 4 大巨蛋散場 | **資料**（歷史峰值） | `policy.check_sop4_trigger` + `traffic_math.station_history` |
| 5 號誌故障 | 事件 | `policy.check_sop5_trigger` |
| 6 數位通報多語化 | **資料**（全市掃描） | `policy.check_sop6_trigger` + `traffic_math.scan_roaming` |
| 7 預計恢復時間 | 事件／分級 | `traffic_math.calculate_ete`，受影響路段定義由 `affected_segments_for_ete` 統一 |

架構圖、職責邊界、資料流與 Demo 前檢查清單見 [`docs/architecture.md`](docs/architecture.md)。

## 資料來源分工

| 資料 | 來源 | 說明 |
|---|---|---|
| `city_traffic_flow.csv` | S3 優先，本地 fallback | 路段飽和度時序 |
| `signaling_crowd_density.csv` | S3 優先，本地 fallback | 捷運站人流密度 |
| `road_network_geometry.json` | S3 優先，本地 fallback | 路網拓樸 |
| `emergency_traffic_sop.txt` | S3 優先，本地 fallback | 交通應變 SOP |
| `live_incidents.json` | **由操作者上傳** | 突發事件，不放 S3 |

前四份參考資料透過 `backend/data_source.py` 解析：設定 `S3_DATA_BUCKET` 時優先讀
S3 並快取到本機，讀取失敗（無 bucket、無權限、物件不存在）會自動退回 `data/` 目錄，
服務不中斷。目前來源狀態可由 `GET /api/health` 的 `data_source` 欄位查看。

突發事件走事件注入介面（見下節），格式為事件陣列或含 `incidents` 的物件；
`data/live_incidents.json` 同時是範例檔與 Dashboard 內建的注入範本，
部署腳本已將它排除在 S3 同步之外。

### 事件注入介面

Dashboard 的「事件注入」頁提供管理員注入 `live_incidents.json`（路面塌陷、人流激增、
號誌故障三類），流程固定為 **目錄 → 預覽 → 確認注入**：

1. `GET /api/incidents/catalog` 提供可引用的路段與人流站點、合法列舉值，以及
   `data/live_incidents.json` 推導出事件分類後的內建範本。
2. `POST /api/incidents/preview`（或上傳檔案的 `/api/incidents/preview/upload`）以
   `backend/incident_response` 的嚴格契約層驗證內容，回傳事件分類、可能適用的 SOP 條號、
   是否含有晚於當下模擬時間的事件，以及注入前必須回覆的確認項目。此步驟不呼叫 Agent。
3. `POST /api/incidents/inject` 重新驗證一次，比對 `preview_hash` 並檢查確認項目後才執行
   應變流程，完成後把建議書寫入注入紀錄並透過 `/ws/dashboard` 推播給所有連線的儀表板。

驗證與分類只有一套實作（`backend/incident_response/payload.py`），注入介面與上傳介面
不會各自長出規則。`POST /api/incidents/inject` 可用 `INCIDENT_INJECT_TOKEN` 加上共用權杖
保護（見 `.env.example`）；未設定時完全開放，適用本機 Demo。

### 60 秒預算

競賽要求 60 秒內產出結果。事件之間併發處理，Bedrock 呼叫由 token bucket 依
`BEDROCK_MIN_CALL_INTERVAL` 間隔送出，以符合基礎模型約每秒一次的呼叫限制。
每個事件只呼叫一次 Bedrock（同時產出建議書敘述與現場處置條列），3 筆事件共 3 次呼叫。

回應帶有 `elapsed_ms` / `elapsed_seconds` / `within_budget`，儀表板會把端到端耗時
顯示在建議書標頭，現場可直接驗證。實測 3 筆官方事件約 18 秒完成（Claude Sonnet 4.6，
`BEDROCK_MAX_TOKENS=1500`）。

## 主要端點

| 方法 | 路徑 | 用途 |
|---|---|---|
| GET | `/api/health` | 容器與 ALB 健康檢查；`?probe=true` 會實際呼叫一次 Bedrock 驗證模型可用 |
| GET | `/api/status` | 路網當下狀態、SOP 第 1 條自動應變、僅監控路段、資料型 SOP 觸發、門檻表 |
| GET | `/api/alert-summary` | 預警 toast 用的 LLM 預警摘要（門檻判定仍由程式運算） |
| GET | `/api/sop` | SOP 條文原文與門檻表 |
| GET | `/api/trend` | 路網時序趨勢（預設不外洩未來資料） |
| GET | `/api/network` | 路網靜態幾何（容量、路口、替代道路） |
| GET | `/api/timeline` | 共同時間軸所有時間點與目前索引 |
| GET | `/api/clock` | 模擬時鐘狀態與時間軸 |
| POST | `/api/clock` | 調整時鐘（mode / sim_time / interval / loop） |
| POST | `/api/clock/advance` | 相對前進或後退（steps / minutes） |
| POST | `/api/clock/pause` | 暫停（凍結模擬時間） |
| POST | `/api/clock/resume` | 繼續播放 |
| POST | `/api/clock/reset` | 回到環境變數初始設定 |
| POST | `/api/incidents` | 處理事件並產生交控建議書 |
| POST | `/api/incidents/upload` | 上傳事件 JSON |
| GET | `/api/incidents/catalog` | 可注入的路段/站點與 `live_incidents.json` 範本 |
| POST | `/api/incidents/preview` | 嚴格驗證事件內容並回傳分類預覽（不執行 Agent） |
| POST | `/api/incidents/preview/upload` | 上傳 `live_incidents.json` 取得同一份預覽 |
| POST | `/api/incidents/inject` | 確認預覽後注入事件並推播給所有儀表板 |
| GET | `/api/incidents/injections` | 近期注入紀錄（可含建議書） |
| POST | `/api/what-if` | 情境問答；可呼叫 `traffic_math` 工具、保留對話記憶、回傳引用條文 |
| POST | `/api/what-if/reset` | 清除指定 session 的對話記憶 |
| WS | `/ws/dashboard` | 模擬時間推進時推播狀態；事件注入完成時推播建議書 |

前端優先走 `/ws/dashboard` 接收推播，連不上或斷線時自動退回 REST 輪詢
（`frontend/src/lib/useLiveStatus.js`），儀表板會顯示目前使用哪一種傳輸。

所有端點都支援 `?ts=YYYY-MM-DD HH:MM` 單次時間覆寫，不影響全域時鐘。FastAPI 互動文件位於 `/docs`。

### 模擬時間模型

模擬時鐘為離散式，只會落在共同時間軸上（目前 14 格，17:00 至 23:15）。共同時間軸的定義是
`city_traffic_flow.csv` 與 `signaling_crowd_density.csv` **兩份來源都有該時間點、且該時間點
的每一列欄位完整、識別碼不重複、數值可解析**。

注意這裡的「完整」是指**欄位完整**，不代表 15 個路段都到齊：資料集本身是稀疏的，
例如 17:00 只有 5 個路段、21:30 有 9 個路段，22:00 之後才是完整 15 段。
未出現的路段在該時間點沒有量測，畫面上就不會出現該路段的卡片。

`SIM_DATA_MODE` 決定讀值語意：

| 模式 | 行為 | 是否觸碰查詢時間之後的資料 |
|---|---|---|
| `asof` | 取 <= 查詢時間的最新一筆，數值呈階梯狀 | 否 |
| `exact` | 只取單一時間點切片 | 否 |
| `interpolate` | 在前後兩筆量測之間線性插值 | **是**（會參考下一筆量測） |

正式部署（`scripts/deploy-ecs-fargate.sh`）固定使用 `asof`，確保絕不使用未來資料。
本機預設為 `interpolate` 以取得平滑曲線；此模式下 `/api/status` 每個路段會帶
`is_interpolated` 與 `interp_weight`，可判斷該數值是量測值還是插值結果。

## 本機開發

先使用 AWS CLI profile 或 SSO 登入，再建立本機設定：

```bash
cp .env.example .env
uv sync --all-groups
```

啟動後端：

```bash
uv run uvicorn backend.main:app --reload --port 8000
```

另一個終端機啟動前端：

```bash
cd frontend
npm ci
npm run dev
```

開啟 `http://localhost:3000`。

## 驗證

```bash
uv run pytest -q
uv run python -m py_compile backend/main.py backend/agents/*.py
cd frontend && npm run build
bash -n scripts/deploy-ecs-fargate.sh
```

## Docker

```bash
docker compose up --build
```

正式映像由 `backend/Dockerfile` 建置，使用 `uv.lock` frozen 同步後端依賴，並將 React 編譯產物複製到 FastAPI 執行映像。

## 部署到 AWS

### 前置需求

- AWS CLI、Docker 與 Docker Buildx。
- 已透過安全的 AWS CLI profile、SSO 或臨時角色完成登入。
- 目標區域可使用 ECR、ECS、EC2、IAM、ALB 與 Bedrock。
- Bedrock 帳號可呼叫 Claude Sonnet 4.6。
- 預設 VPC 至少有兩個位於不同可用區的子網路。

請勿將 AWS access key、secret key 或 session token 寫入 `.env`、映像、原始碼或聊天訊息。

### ECS Fargate 部署

```bash
AWS_PROFILE=city-commander-deploy AWS_REGION=us-west-2 \
  bash scripts/deploy-ecs-fargate.sh
```

部署腳本會：

1. 建置 `linux/amd64` 全端映像並推送至 ECR。
2. 建立或更新 ECS 任務執行角色與最小 Bedrock 呼叫權限。
3. 建立或沿用 ECS cluster、Fargate service、安全群組、ALB、Target Group 與 Listener。
4. 註冊新版任務定義並執行滾動部署。
5. 等待服務穩定後輸出 Dashboard 與健康檢查網址。

### 部署後測試

將部署腳本輸出的網址設為服務入口後執行：

```bash
curl -fsS http://YOUR_ALB_DNS/api/health
curl -fsS http://YOUR_ALB_DNS/api/status
curl -fsS -H 'Content-Type: application/json' \
  -d '{"prompt":"請判斷目前完整路網狀態並下達行動指令。","session_id":"smoke-test"}' \
  http://YOUR_ALB_DNS/api/what-if
```

瀏覽器可開啟 `http://YOUR_ALB_DNS/` 與 `http://YOUR_ALB_DNS/docs`。目前 ALB 使用 HTTP；正式對外上線前應配置自有網域、ACM 憑證與 HTTPS Listener。

## 專案結構

```text
city-commander-agent/
├── backend/
│   ├── main.py                  # FastAPI、API、WebSocket、前端靜態服務
│   ├── sim_clock.py             # 離散模擬時鐘與共同時間軸
│   ├── agents/
│   │   ├── sop_rules.py         # SOP 門檻常數、事件分類、上下游判定（規則單一來源）
│   │   ├── traffic_math.py      # 唯一數值計算模組（分級、路徑、ETE、漫遊、號誌）
│   │   ├── policy.py            # SOP 1~7 觸發判定與條文原文擷取
│   │   ├── router.py            # 路徑與 ETE 組裝
│   │   ├── comms.py             # 四語 CMS 與民眾簡訊
│   │   ├── advisor_tools.py     # What-if 顧問可呼叫的計算工具
│   │   └── architect.py         # 總指揮、預警摘要、What-if
│   ├── incident_response/       # 事件注入契約層（驗證、預覽、注入紀錄）
│   └── Dockerfile               # React + FastAPI 正式單一映像
├── frontend/                    # React Dashboard
├── data/                        # SOP、路網、流量與人流資料
├── docs/
│   └── architecture.md          # AWS 架構圖、職責邊界、資料流、Demo 檢查清單
├── tests/
│   ├── backend/agents/          # SOP 1~7 逐條黃金案例
│   └── backend/incident_response/  # 契約、parser、時鐘、快照
├── deployment/iam/              # 受管服務信任與 Bedrock IAM policy
├── scripts/
│   └── deploy-ecs-fargate.sh    # 正式 AWS 部署腳本
├── docker-compose.yml           # 本機容器環境
├── pyproject.toml
├── uv.lock
└── .env.example
```
