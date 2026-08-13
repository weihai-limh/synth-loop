# synth-loop 官方 Docker 镜像
#
# 构建：
#   docker build -f deploy/container/Dockerfile -t synth-loop:latest .
#
# 运行（内置数据目录自动创建）：
#   docker run -d -p 13155:13155 synth-loop:latest
#
# 运行（外挂数据目录，数据持久化）：
#   docker run -d -p 13155:13155 \
#     -v /host/path/to/data:/app/src/data \
#     -e OPENAI_API_KEY=sk-xxx \
#     synth-loop:latest

FROM python:3.13-slim

# ── 安装系统依赖 ──────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ── 安装 Python 依赖 ──────────────────────────────────────
COPY src/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# ── 复制源码 ──────────────────────────────────────────────
COPY src/ /app/src/
WORKDIR /app/src

# ── 环境变量 ──────────────────────────────────────────────
ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

# ── 数据目录（volume 挂载点，容器内外共享） ──────────────
RUN mkdir -p /app/src/data
VOLUME ["/app/src/data"]

EXPOSE 13155

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:13155/health || exit 1

# 数据库由 app.main 在 lifespan 中自动初始化（幂等）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "13155"]
