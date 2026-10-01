FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120

WORKDIR /app

RUN addgroup --system hookrelay && adduser --system --ingroup hookrelay hookrelay

COPY pyproject.toml README.md ./
COPY hookrelay ./hookrelay
COPY alembic.ini ./
COPY migrations ./migrations

RUN --mount=type=cache,target=/root/.cache/pip pip install .

USER hookrelay

FROM base AS test

USER root
COPY tests ./tests
RUN --mount=type=cache,target=/root/.cache/pip pip install ".[dev]" \
    && ruff check . \
    && ruff format --check . \
    && pytest

FROM base AS production

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn hookrelay.main:app --host 0.0.0.0 --port 8000"]

