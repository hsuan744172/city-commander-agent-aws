# Build the React dashboard first so ECS Fargate can serve the complete application.
FROM node:22-slim AS frontend-build
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# MapLibre 6 經 bundler 必須有獨立 worker；缺檔時 production 會只剩空白底圖。
# 在映像建置階段直接阻擋不完整的前端產物進入 ECR。
RUN npm run build \
    && find dist/assets -maxdepth 1 -type f -name 'maplibre-gl-worker-*.js' -print -quit | grep -q .

# Supply a pinned uv binary to the production image.
FROM ghcr.io/astral-sh/uv:0.10.0 AS uv

# Run FastAPI and serve the compiled dashboard from the same origin.
FROM python:3.13-slim
WORKDIR /app

COPY --from=uv /uv /uvx /usr/local/bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY backend/ ./backend/
COPY data/ ./data/
COPY --from=frontend-build /frontend/dist ./frontend_dist/

ENV PATH="/app/.venv/bin:${PATH}"
ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
