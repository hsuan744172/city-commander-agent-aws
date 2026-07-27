# 城市應變指揮官 (City Commander Agent)

AI 驅動的智慧交通應變指揮系統，具備即時感知、極速決策、跨域協調能力。

## Tech Stack

| 層級 | 技術 |
|------|------|
| Frontend | React 19 + Vite 6 + Tailwind CSS 4 |
| Backend | FastAPI + Python 3.13 |
| AI | Strands Agents SDK (Bedrock Claude) / Google Gemini (本地開發) |
| 部署 | Docker + AWS App Runner |

## 功能模組

1. **動態路網監測** — 15 路段即時飽和度儀表板，異常自動警報
2. **突發事件應變** — 一鍵注入事件，AI 秒級產出交控中心建議書
3. **AI 策略對話** — What-if 假設情境問答
4. **多語化通報** — 繁中/英/日/韓四語 CMS 訊息，一鍵發布

## 本地開發

```bash
# 環境設定
cp .env.example .env
# 編輯 .env 填入 GEMINI_API_KEY

# Backend
poetry install
poetry run uvicorn backend.main:app --reload --port 8000

# Frontend
cd frontend && npm install && npm run dev
```

開啟 http://localhost:3000

## Docker

```bash
docker compose up --build
```

## 部署到 AWS App Runner

1. 推送到 GitHub Private Repo
2. AWS Console → App Runner → Create Service → Source: GitHub
3. 選擇此 repo，指定 `backend/Dockerfile`
4. 設定環境變數：`LLM_PROVIDER=bedrock`、`BEDROCK_MODEL_ID`、`APP_AWS_REGION`
5. App Runner 自動 build + deploy，產出 HTTPS URL

Frontend 可用 Amplify Hosting 或 S3 + CloudFront 部署靜態檔。

## 專案結構

```
├── backend/          # FastAPI + AI Agents
│   ├── main.py
│   └── agents/       # architect, policy, router, comms, traffic_math
├── frontend/         # React Dashboard
│   └── src/components/
├── data/             # 交通資料 (CSV, JSON, TXT)
├── docker-compose.yml
├── apprunner.yaml
└── .env.example
```
