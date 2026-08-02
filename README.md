# 城市應變指揮官 (City Commander Agent)

AI 驅動的智慧交通應變指揮系統：即時感知、決策支援、替代路徑規劃與多語公眾通報。

線上環境：<http://city-commander-alb-272857069.us-west-2.elb.amazonaws.com>（us-west-2）

## 技術架構

| 層級 | 技術 |
|---|---|
| Frontend | React 19、Vite 6、Tailwind CSS 4、MapLibre／Leaflet |
| Backend | FastAPI、uvicorn、Python 3.13 |
| AI | Strands Agents SDK、Amazon Bedrock Claude（`us.anthropic.claude-sonnet-4-6`） |
| Python 管理 | uv、`uv.lock` |
| 容器 | Docker 多階段建置的**單一 all-in-one 映像** |
| AWS | ECR、ECS Fargate、Application Load Balancer、S3、CloudWatch Logs、IAM |

正式環境只跑一個容器：建置階段先 `npm run build` 編譯 React Dashboard，
再放進 FastAPI 映像的 `frontend_dist/`，執行時由 FastAPI 用 StaticFiles 同源提供前端，
`/api/*` 與 `/ws/dashboard` 因此都是同源，不需要反向代理或第二個容器。
映像推送到 ECR，由 ECS Fargate 執行，internet-facing ALB 負責公開入口與健康檢查。

```text
Internet
  │ HTTP / WebSocket :80
  ▼
Application Load Balancer            SG: 0.0.0.0/0 → :80
  │ forward :8080，health check /api/health
  ▼
ECS Fargate task（1024 CPU / 2048 MB）SG: 僅 ALB → :8080
  └── 單一容器 :8080
      ├── React Dashboard（靜態檔）
      ├── FastAPI REST / WebSocket
      └── Strands Agents + 模擬時鐘
              │
              ├── Amazon Bedrock（InvokeModel）
              ├── Amazon S3（資料集唯讀）
              └── CloudWatch Logs
```

完整架構圖（Mermaid）、五大模組對照、職責邊界、資料流與 Demo 檢查清單見
[`docs/architecture.md`](docs/architecture.md)。

## 功能模組

1. **動態時序監測儀表板**：依模擬時鐘呈現路段飽和度、速度、車流與 A/B 級分級，
   附時間軸控制列可暫停、回放、跳至指定時間點，並可查看路段鄰近的即時街景影像。
2. **主動預警**：達 SOP 門檻時在儀表板顯示不遮蔽畫面的預警 toast。門檻判定由程式運算、
   摘要由 LLM 生成（`GET /api/alert-summary`）。人流與信令的 SOP 第 3、4、6 條
   **不需要事件注入**即會主動偵測。
3. **突發事件應變（60 秒內）**：三段式注入（目錄 → 預覽 → 確認注入），產出「交控中心建議書」
   並回報端到端耗時。
4. **對話式策略諮詢顧問**：What-if 顧問呼叫路網計算工具取得確定性結果，保留對話記憶，
   並附上實際引用的 SOP 條文原文。
5. **AI 決策推理與解釋鏈**：每份建議書帶 `decision_trace` 與 `sop_conformance`，
   逐步列出輸入值、門檻比對、引用條文，以及每個候選替代道路被選用或排除的理由與 ETE。
6. **多語化全通路通報**：全市任一基地台漫遊率達 30% 觸發 SOP 第 6 條，產生繁中、英、日、韓
   的 CMS 看板文字與民眾簡訊。

### SOP 條款實作對照

| 條款 | 觸發來源 | 實作位置 |
|---|---|---|
| 1 交通擁塞級別 | 車流飽和度 | `sop_rules.assess_congestion_level`；城市應變限於觸發路段 `RD_TPE_001`、`RD_TPE_002` |
| 2 車禍與路障 | 事件 | `policy.check_sop2_trigger` + `traffic_math.calculate_optimal_route` |
| 3 捷運與接駁分流 | **資料** | `policy.check_sop3_trigger`（儀表板主動偵測） |
| 4 大巨蛋散場 | **資料**（歷史峰值） | `policy.check_sop4_trigger` + `traffic_math.station_history` |
| 5 號誌故障 | 事件 | `policy.check_sop5_trigger` |
| 6 數位通報多語化 | **資料**（全市掃描） | `policy.check_sop6_trigger` + `traffic_math.scan_roaming` |
| 7 預計恢復時間 | 事件／分級 | `traffic_math.calculate_ete`，受影響路段由 `affected_segments_for_ete` 統一定義 |

## 資料來源分工

| 資料 | 來源 | 說明 |
|---|---|---|
| `city_traffic_flow.csv` | S3 優先，本地 fallback | 路段飽和度時序 |
| `signaling_crowd_density.csv` | S3 優先，本地 fallback | 捷運站人流與漫遊 |
| `road_network_geometry.json` | S3 優先，本地 fallback | 路網拓樸 |
| `emergency_traffic_sop.txt` | S3 優先，本地 fallback | 交通應變 SOP |
| `segment_cameras.json` | S3 優先，本地 fallback | 路段對應即時影像攝影機 |
| `segment_coordinates.json` | 只在本地使用 | 路段座標，`scripts/build_camera_map.py` 產生攝影機對照表的輸入 |
| `live_incidents.json` | **不放 S3** | 事件注入範本，由操作者選用或上傳 |

`backend/data_source.py` 統一取用：設定 `S3_DATA_BUCKET` 時優先讀 S3 並快取到本機，
讀取失敗（無桶、無權限、物件不存在）自動退回映像內的 `data/`，服務不中斷。
目前來源可由 `GET /api/health` 的 `data_source` 欄位查看。部署腳本同步 `data/` 到 S3 時
已排除 `live_incidents.json`。

### 事件注入介面

Dashboard 的「事件注入」頁供管理員注入 `live_incidents.json`（路面塌陷、人流激增、
號誌故障三類），流程固定為 **目錄 → 預覽 → 確認注入**：

1. `GET /api/incidents/catalog`：可引用的路段與人流站點、合法列舉值，以及
   `data/live_incidents.json` 推導出事件分類後的內建範本。
2. `POST /api/incidents/preview`（或上傳檔案的 `/api/incidents/preview/upload`）：以
   `backend/incident_response` 的嚴格契約層驗證內容，回傳事件分類、可能適用的 SOP 條號、
   是否含有晚於當下模擬時間的事件，以及注入前必須回覆的確認項目。此步驟不呼叫 Agent。
3. `POST /api/incidents/inject`：重新驗證一次，比對 `preview_hash` 與確認項目後才執行
   應變流程，完成後寫入注入紀錄，並透過 `/ws/dashboard` 廣播 `incident_report`
   給所有連線的儀表板。

驗證與分類只有一套實作（`backend/incident_response/payload.py`），注入與上傳兩條路徑
不會各自長出規則。`POST /api/incidents/inject` 可用 `INCIDENT_INJECT_TOKEN` 設共用權杖
保護（請求帶 `X-Admin-Token`）；未設定時完全開放，適用本機 Demo。

### 60 秒預算

事件之間併發處理，Bedrock 呼叫由 token bucket 依 `BEDROCK_MIN_CALL_INTERVAL` 間隔送出，
以符合基礎模型約每秒一次的呼叫限制。每個事件只呼叫一次 Bedrock（同時產出建議書敘述與
現場處置條列），3 筆事件共 3 次呼叫。

回應帶 `elapsed_ms` / `elapsed_seconds` / `within_budget`，儀表板把端到端耗時顯示在
建議書標頭，現場可直接驗證。實測 3 筆官方事件約 18 秒完成（`BEDROCK_MAX_TOKENS=1500`）。

## 主要端點

| 方法 | 路徑 | 用途 |
|---|---|---|
| GET | `/api/health` | 容器與 ALB 健康檢查；`?probe=true` 會實際呼叫一次 Bedrock 驗證模型可用 |
| GET | `/api/status` | 路網當下狀態、SOP 第 1 條自動應變、僅監控路段、資料型 SOP 觸發、門檻表 |
| GET | `/api/alert-summary` | 預警 toast 用的 LLM 預警摘要（門檻判定仍由程式運算） |
| GET | `/api/sop` | SOP 條文原文與門檻表 |
| GET | `/api/trend` | 路網時序趨勢（預設不外洩未來資料） |
| GET | `/api/network` | 路網靜態幾何（容量、路口、替代道路） |
| GET | `/api/stream` | 串流播放狀態（循環播放的 live 邊界與時間軸） |
| GET | `/api/timeline` | 共同時間軸所有時間點與目前索引 |
| GET | `/api/cameras` | 全路段即時影像攝影機對照表 |
| GET | `/api/cameras/{segment_id}` | 單一路段鄰近攝影機 |
| GET | `/api/cameras/{segment_id}/{camera_id}/stream` | MJPEG 代理串流 |
| GET | `/api/cameras/{segment_id}/{camera_id}/snapshot` | 單張畫面 |
| GET | `/api/cameras/{segment_id}/{camera_id}/frame` | 畫面年齡與上游狀態 |
| GET | `/api/clock` | 模擬時鐘狀態與時間軸 |
| POST | `/api/clock` | 調整時鐘（mode / sim_time / interval / loop） |
| POST | `/api/clock/advance` | 相對前進或後退（steps / minutes） |
| POST | `/api/clock/pause` | 暫停（凍結模擬時間） |
| POST | `/api/clock/resume` | 繼續播放 |
| POST | `/api/clock/reset` | 回到環境變數初始設定 |
| GET | `/api/incidents/catalog` | 可注入的路段／站點與 `live_incidents.json` 範本 |
| POST | `/api/incidents/preview` | 嚴格驗證事件內容並回傳分類預覽（不執行 Agent） |
| POST | `/api/incidents/preview/upload` | 上傳 `live_incidents.json` 取得同一份預覽 |
| POST | `/api/incidents/inject` | 確認預覽後注入事件並推播給所有儀表板 |
| GET | `/api/incidents/injections` | 近期注入紀錄（可含建議書） |
| POST | `/api/what-if` | 情境問答；可呼叫 `traffic_math` 工具、保留對話記憶、回傳引用條文 |
| POST | `/api/what-if/reset` | 清除指定 session 的對話記憶 |
| WS | `/ws/dashboard` | 模擬時間推進時推播 `status`；事件注入完成時推播 `incident_report` |

前端優先走 `/ws/dashboard` 接收推播，連不上或斷線時自動退回 REST 輪詢
（`frontend/src/lib/useLiveStatus.js`），儀表板會顯示目前使用哪一種傳輸。

所有端點支援 `?ts=YYYY-MM-DD HH:MM` 單次時間覆寫，不影響全域時鐘。
FastAPI 互動文件在 `/docs`。

### 模擬時間模型

模擬時鐘為離散式，只落在共同時間軸上（目前 14 格，17:00 至 23:15）。共同時間軸的定義是
`city_traffic_flow.csv` 與 `signaling_crowd_density.csv` **兩份來源都有該時間點、且該時間點
每一列欄位完整、識別碼不重複、數值可解析**。

「完整」指**欄位完整**，不代表 15 個路段都到齊：資料集本身稀疏，例如 17:00 只有 5 個路段、
21:30 有 9 個路段，22:00 之後才是完整 15 段。未出現的路段在該時間點沒有量測，畫面上不會出現。

`SIM_DATA_MODE` 決定讀值語意：

| 模式 | 行為 | 是否觸碰查詢時間之後的資料 |
|---|---|---|
| `asof` | 取 <= 查詢時間的最新一筆，數值呈階梯狀 | 否 |
| `exact` | 只取單一時間點切片 | 否 |
| `interpolate` | 在前後兩筆量測之間線性插值 | **是**（會參考下一筆量測） |

正式部署固定使用 `asof`，確保絕不使用未來資料。本機預設 `interpolate` 以取得平滑曲線；
此模式下 `/api/status` 每個路段會帶 `is_interpolated` 與 `interp_weight`。

## 本機啟動

先用 AWS CLI profile 或 SSO 登入（Bedrock 需要憑證），再建立本機設定：

```bash
cp .env.example .env
uv sync
```

啟動後端（預設 8000）：

```bash
uv run uvicorn backend.main:app --reload --port 8000
```

另一個終端機啟動前端開發伺服器（Vite 已把 `/api` 與 `/ws` 代理到 8000）：

```bash
cd frontend
npm ci
npm run dev
```

開啟 <http://localhost:3000>。

也可以直接跑容器版本，前端在 3000、後端在 8080（需要先有 `.env`）：

```bash
docker compose up --build
```

### 建置檢查

```bash
uv run python -m py_compile backend/main.py backend/agents/*.py
cd frontend && npm run build
bash -n scripts/deploy-ecs-fargate.sh
```

## 部署到 AWS

### 前置需求

- AWS CLI、Docker 與 Docker Buildx、`jq`（驗證用）。
- 已透過 AWS CLI profile、SSO 或臨時角色完成登入。
- 目標區域可使用 ECR、ECS、EC2、ELB、IAM、S3、CloudWatch Logs 與 Bedrock。
- Bedrock 帳號可呼叫 Claude Sonnet 4.6（`us.anthropic.claude-sonnet-4-6`）。
- 預設 VPC 至少有兩個位於不同可用區的 default subnet。

請勿把 AWS access key、secret key 或 session token 寫進 `.env`、映像、原始碼或聊天訊息。

### 一鍵部署

```bash
AWS_PROFILE=city-commander-deploy AWS_REGION=us-west-2 \
  bash scripts/deploy-ecs-fargate.sh
```

腳本會建立或更新以下資源（可重複執行）：

1. S3 資料桶（public access block、AES256 加密），並 `aws s3 sync data/`（排除 `live_incidents.json`）。
2. CloudWatch Logs group `/ecs/city-commander-agent`，保留 14 天。
3. ECR repo，並以 `linux/amd64` 建置 `backend/Dockerfile` 全端映像後推送。
4. 兩個 IAM role：`CityCommanderEcsTaskExecutionRole`（拉映像、寫日誌）與
   `CityCommanderEcsTaskRole`（Bedrock InvokeModel + 該桶前綴的 S3 唯讀）。
5. ECS cluster、default VPC 兩個 subnet、ALB 安全群組（開 80）與 task 安全群組（僅允許 ALB 連 8080）。
6. ALB、target group（health check `/api/health`）與 listener。
7. Task definition（1024 CPU / 2048 memory、`SIM_DATA_MODE=asof`）與 ECS service（desired count 1），
   滾動部署後等待服務穩定，最後輸出 Dashboard 與健康檢查網址。

常用覆寫：`SERVICE_NAME`、`CLUSTER_NAME`、`ECR_REPOSITORY`、`BEDROCK_MODEL_ID`、
`BEDROCK_MAX_TOKENS`、`S3_DATA_BUCKET`、`S3_DATA_PREFIX`、`SIM_CLOCK_INTERVAL`、`SIM_CLOCK_LOOP`。

### 部署後驗證

```bash
BASE=http://YOUR_ALB_DNS

curl -fsS "$BASE/api/health" | jq '{status, data_source, bedrock}'
curl -fsS "$BASE/api/health?probe=true" | jq .bedrock_probe
curl -fsS "$BASE/api/status" | jq '{sim_time, data_mode, sop: .data_triggers.triggered_numbers}'
curl -fsS -X POST "$BASE/api/what-if" -H 'Content-Type: application/json' \
  -d '{"prompt":"請判斷目前完整路網狀態並下達行動指令。","session_id":"smoke-test"}' \
  | jq '{response, tools_used, cited: [.cited_clauses[].sop_number]}'
```

瀏覽器可開啟 `$BASE/` 與 `$BASE/docs`。事件注入的端到端 60 秒驗證指令見
[`docs/architecture.md`](docs/architecture.md) 的 Demo 前檢查清單。

ALB 目前只有 HTTP listener；正式對外上線前應配置自有網域、ACM 憑證與 HTTPS listener。

## 專案結構

```text
city-commander-agent/
├── backend/
│   ├── main.py                  # FastAPI 路由、WebSocket、模擬時鐘端點、前端靜態服務
│   ├── sim_clock.py             # 程序內離散模擬時鐘與共同時間軸
│   ├── data_source.py           # 資料取用：S3 優先、本地 fallback
│   ├── camera_stream.py         # 街景 MJPEG 代理（網址僅來自對照表白名單）
│   ├── mock_camera.py           # 上游不可用時的模擬影像
│   ├── agents/
│   │   ├── sop_rules.py         # SOP 門檻常數、事件分類、上下游判定
│   │   ├── traffic_math.py      # 唯一數值計算模組（分級、路徑、ETE、漫遊、號誌）
│   │   ├── policy.py            # SOP 1~7 觸發判定與條文原文擷取
│   │   ├── router.py            # 路徑與 ETE 組裝
│   │   ├── comms.py             # 四語 CMS 與民眾簡訊
│   │   ├── decision_trace.py    # 決策鏈與 SOP 合規投影
│   │   ├── advisor_tools.py     # What-if 顧問可呼叫的計算工具
│   │   └── architect.py         # 總指揮、預警摘要、Bedrock 呼叫
│   ├── incident_response/       # 事件注入嚴格契約層（domain/payload/sources/snapshot/injection/config）
│   ├── serverless/              # 原生 Lambda handler（另一條路線，非目前 ECS 部署使用）
│   └── Dockerfile               # React + FastAPI 正式單一映像
├── frontend/                    # React Dashboard（Vite）
├── data/                        # SOP、路網、流量、人流、攝影機與座標資料
├── docs/
│   └── architecture.md          # 架構圖、五大模組對照、職責邊界、資料流、Demo 檢查清單
├── deployment/iam/              # Bedrock IAM policy
├── scripts/
│   ├── deploy-ecs-fargate.sh    # 正式 AWS 部署腳本
│   └── build_camera_map.py      # 由路段座標產生攝影機對照表（離線工具）
├── docker-compose.yml           # 本機容器環境
├── pyproject.toml
├── uv.lock
└── .env.example
```
