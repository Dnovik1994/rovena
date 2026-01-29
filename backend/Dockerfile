FROM python:3.12-slim

WORKDIR /app

ARG COMMIT_SHA=unknown
ENV COMMIT_SHA=${COMMIT_SHA}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic
COPY entrypoint.sh /entrypoint.sh
COPY scripts /app/scripts

RUN chmod +x /entrypoint.sh /app/scripts/*.sh \
    && adduser --disabled-password --gecos "" appuser \
    && chown -R appuser /app

USER appuser

ENTRYPOINT ["/entrypoint.sh"]
