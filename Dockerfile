FROM python:3.12-slim AS builder

WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv build --wheel && uv pip install --system dist/*.whl

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PORT=8080 GITCRAWL_GOOGLE_VERTEXAI=true HOME=/tmp
WORKDIR /tmp
COPY --from=builder /usr/local /usr/local
USER 65532:65532
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT} --worker-tmp-dir /tmp --workers 1 --threads 8 --timeout 900 gitcrawl.hosted.app:app"]
