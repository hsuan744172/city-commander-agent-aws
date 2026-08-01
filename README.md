# 城市應變指揮官 (City Commander Agent)

AI 驅動的智慧交通應變指揮系統，提供即時感知、極速決策與跨域協調。

## 技術架構

| 層級 | 技術 |
|---|---|
| Frontend | React 19、Vite 6、Tailwind CSS 4 |
| Backend | FastAPI、Python 3.13 |
| AI | Strands Agents SDK、Amazon Bedrock Claude Sonnet 5 |
| Python 管理 | uv |
| 部署 | Docker、AWS App Runner |

## 功能模組

1. **動態路網監測**：15 個路段的即時飽和度儀表板與異常警報。
2. **突發事件應變**：注入事件後產出交控中心建議書。
3. **AI 策略對話**：What-if 情境問答。
4. **多語化通報**：繁中、英、日、韓 CMS 訊息與一鍵發布。

## 本機開發

```bash
# 設定 Bedrock 的區域與模型；本機 AWS 身分請使用 AWS CLI profile 或 SSO。
cp .env.example .env

# 建立／同步包含開發工具的 uv 虛擬環境。
uv sync --all-groups

# 啟動 FastAPI。
uv run uvicorn backend.main:app --reload --port 8000

# 另一個終端機：啟動 React 開發伺服器。
cd frontend && npm ci && npm run dev
```

開啟 `http://localhost:3000`。

## 驗證

```bash
uv run pytest -q
uv run python -m py_compile backend/main.py backend/agents/architect.py
cd frontend && npm run build
```

## Docker

```bash
docker compose up --build
```

Docker production image 使用 `uv.lock` 以 frozen 模式同步後端依賴，並把編譯後的 React dashboard 與 FastAPI 一起提供。

## 部署到 AWS App Runner

部署前請以安全的 AWS CLI profile 或 SSO 登入，並確認帳號已取得 `us-west-2` 中 Claude Sonnet 5 的 Bedrock 模型存取權。請勿把 AWS access key 或 session token 寫入 `.env`、Docker image 或聊天訊息。

```bash
AWS_PROFILE=city-commander-deploy AWS_REGION=us-west-2 \
  bash scripts/deploy-apprunner.sh
```

部署 script 會建立或更新 ECR repository、App Runner 的 ECR access role、Bedrock instance role 與 App Runner service；完成後會輸出 HTTPS 服務 URL 和 `/api/health` 檢查網址。

## 專案結構

```text
├── backend/          # FastAPI + AI agents
├── frontend/         # React dashboard
├── data/             # 交通與 SOP 資料
├── deployment/iam/   # App Runner 與 Bedrock IAM policies
├── scripts/          # 部署自動化
├── docker-compose.yml
├── pyproject.toml
├── uv.lock
└── .env.example
```
