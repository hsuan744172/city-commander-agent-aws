# 城市應變指揮官 (City Commander Agent) — 全局產品指引 v2

## 核心目標

打造具備「主動感知、極速決策、跨域協調」的 AI 交通指揮中心。

1. **即時事件偵測與分級** — 自動判定交通癱瘓等級（A / B 級）
2. **法規 SOP 比對與觸發** — 自動識別應觸發之 SOP 條款（第 2、3、5、6 條）
3. **替代路徑計算與 ETE 估算** — 篩選主疏散路段並計算預估恢復時間
4. **多語系公眾通報** — 繁中/英/日/韓四語公告訊息

最終產出：「交控中心建議書」JSON，透過 Dashboard 即時呈現。

---

## 技術架構 (v2)

```
Frontend (React + Vite + Tailwind CSS)
       │ HTTP POST / WebSocket
       ▼
Backend (FastAPI + Strands Agents SDK)
  ├── POST /api/incidents   → Architect Agent
  ├── POST /api/what-if     → What-if 問答
  ├── GET  /api/status      → 路網即時狀態
  └── WS   /ws/dashboard    → 即時推播
       │
       ├── Policy Agent (SOP 判定, 本地 SOP 讀取)
       ├── Router Agent (路徑 + ETE, traffic_math 模組)
       └── Comms Agent (多語通報, 漫遊率查詢)

部署：Docker → AWS App Runner
```

---

## 資料環境

| 資料檔案 | 用途 |
|----------|------|
| `data/city_traffic_flow.csv` | 即時路段飽和度 |
| `data/live_incidents.json` | 即時突發事件 |
| `data/road_network_geometry.json` | 路網拓樸 |
| `data/signaling_crowd_density.csv` | 捷運站人流密度 |
| `data/emergency_traffic_sop.txt` | 官方交通應變 SOP |

---

## 全局邊界約束

### 約束 1：嚴禁數學幻覺

所有數值計算（飽和度比對、ETE、路徑篩選）只在 `backend/agents/traffic_math.py` 執行。
Agent 僅負責組裝參數與解讀回傳值。

### 約束 2：時間格式統一

所有對外輸出時間欄位一律 **`YYYY-MM-DD HH:MM`**。

### 約束 3：公眾訊息範本

- 一般事故：`「<事故路段>封閉，請改道 <主疏散路段>，預計延誤 <ETE> 分鐘」`
- 號誌故障：`「<路段> 號誌故障，請依現場指揮通行」`

### 約束 4：多語系觸發

漫遊率 >= 30% → SOP 第 6 條 → 繁中/英/日/韓四語。

### 約束 5：路段篩選邏輯

1. `capacity_vph` >= 1000
2. 位於事故點 intersections 上游
3. 當前 Saturation_Score 最低者

### 約束 6：ETE 公式

```
ETE_minutes = base_clearance + congestion_penalty
  Critical → 60, High → 40, Medium → 20
  congestion_penalty = max(0, (avg_saturation - 0.5) × 60)
```

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

### 約束 9：Fallback 機制 (路徑篩選)

當 SOP 第 2 條嚴格篩選無完全符合者時，依序退階：
1. 取下游相交路段中飽和度最低者
2. 取所有替代路段中容量 ≥ 1000 且飽和度最低者
3. 絕不回傳空值，至少提供一條建議路段並標註「Fallback」

---

## 開發指令

```bash
# 本地開發 (backend)
cd backend && pip install -r requirements.txt
uvicorn backend.main:app --reload

# 本地開發 (frontend)
cd frontend && npm install && npm run dev

# Docker 全端
docker compose up --build

# 部署到 App Runner
# 推送到 GitHub/CodeCommit → App Runner 自動偵測 Dockerfile 並部署
```

---

## 專案結構

```
city-commander-agent/
├── backend/
│   ├── main.py              # FastAPI 入口
│   ├── agents/
│   │   ├── architect.py     # 總指揮
│   │   ├── policy.py        # 法規驗證
│   │   ├── router.py        # 路網計算
│   │   ├── comms.py         # 多語通報
│   │   └── traffic_math.py  # 數學計算模組
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   └── components/
│   ├── package.json
│   ├── Dockerfile
│   └── nginx.conf
├── data/                    # 交通資料
├── docker-compose.yml
├── apprunner.yaml
└── pyproject.toml
```
