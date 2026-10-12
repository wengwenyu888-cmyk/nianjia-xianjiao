# 后端镜像：多阶段构建，uv 装依赖，运行镜像不含构建工具链
# 构建：docker build -f deploy/Dockerfile -t nianjia-api ./backend

# ---------- 阶段 1：依赖构建 ----------
FROM python:3.12-slim AS builder

# uv 官方静态二进制（pip 源复制，避免因网络问题构建失败）
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# 先只拷贝依赖描述文件，最大化利用 Docker 层缓存
# 注意：首次构建前需在 backend/ 执行 uv lock 生成 uv.lock
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# 再拷贝应用代码并安装项目自身
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ---------- 阶段 2：运行 ----------
FROM python:3.12-slim AS runtime

# 非 root 运行；固定 uid 便于挂载卷权限管理
RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid 1000 --create-home appuser

WORKDIR /app

# 只搬运虚拟环境与应用代码，不带 uv 与构建缓存
COPY --from=builder --chown=appuser:appuser /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER appuser
EXPOSE 8000

# 存活探针走 /api/v1/health（不依赖数据库）
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=2).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
