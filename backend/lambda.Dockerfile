FROM ghcr.io/astral-sh/uv:0.12.1 AS uv

FROM public.ecr.aws/lambda/python:3.13

COPY --from=uv /uv /uvx /usr/local/bin/
WORKDIR ${LAMBDA_TASK_ROOT}

COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project --format requirements-txt --output-file /tmp/requirements.txt \
    && uv pip install --system --no-cache --requirements /tmp/requirements.txt \
    && rm -f /tmp/requirements.txt

COPY backend/ ./backend/
COPY data/ ./data/

CMD ["backend.serverless.monitoring_handler.lambda_handler"]
