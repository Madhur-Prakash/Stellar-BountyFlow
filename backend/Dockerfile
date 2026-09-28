# syntax=docker/dockerfile:1.7
# BountyFlow API image. Also used by the `migrate` service (`alembic upgrade head`).

# --- Build: resolve the locked dependency set into a virtualenv ------------------------------------
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3.12 \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app

# Dependencies first (cached until pyproject.toml / uv.lock change).
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project

COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# --- Runtime ----------------------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:${PATH}" \
    APP_ENV=production

RUN groupadd --system --gid 10001 bountyflow \
    && useradd --system --uid 10001 --gid bountyflow --home-dir /app --shell /usr/sbin/nologin bountyflow

WORKDIR /app
COPY --from=builder --chown=bountyflow:bountyflow /opt/venv /opt/venv
COPY --from=builder --chown=bountyflow:bountyflow /app /app

USER bountyflow

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
