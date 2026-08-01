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

1. **動態路網監測**：呈現 15 個路段的飽和度、速度、車流與異常警報。
2. **突發事件應變**：注入或上傳事件後，產出「交控中心建議書」JSON。
3. **AI 策略對話**：依本地 SOP 與完整路網資料提供 What-if 決策支援。
4. **替代路徑與 ETE**：由專用交通數學模組執行路徑篩選與恢復時間估算。
5. **多語公眾通報**：依 SOP 產生繁中、英、日、韓公告。

## 主要端點

| 方法 | 路徑 | 用途 |
|---|---|---|
| GET | `/api/health` | 容器與 ALB 健康檢查 |
| GET | `/api/status` | 最新完整路網狀態與自動建議 |
| GET | `/api/trend` | 路網時序趨勢 |
| POST | `/api/incidents` | 處理事件並產生交控建議書 |
| POST | `/api/incidents/upload` | 上傳事件 JSON |
| POST | `/api/what-if` | Bedrock 情境問答 |
| WS | `/ws/dashboard` | Dashboard 即時推播 |

FastAPI 互動文件位於 `/docs`。

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
│   ├── agents/
│   │   ├── architect.py         # 總指揮與 What-if
│   │   ├── policy.py            # SOP 驗證
│   │   ├── router.py            # 路由 Agent
│   │   ├── comms.py             # 多語通報 Agent
│   │   └── traffic_math.py      # 唯一數值計算模組
│   └── Dockerfile               # React + FastAPI 正式單一映像
├── frontend/                    # React Dashboard
├── data/                        # SOP、路網、流量與人流資料
├── deployment/iam/              # 受管服務信任與 Bedrock IAM policy
├── scripts/
│   └── deploy-ecs-fargate.sh    # 正式 AWS 部署腳本
├── docker-compose.yml           # 本機容器環境
├── pyproject.toml
├── uv.lock
└── .env.example
```
