FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim

WORKDIR /app

ARG COMMIT_SHA=unknown
ENV COMMIT_SHA=${COMMIT_SHA}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

COPY --from=builder /install /usr/local

COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic
COPY entrypoint.sh /entrypoint.sh
COPY scripts /app/scripts

RUN python - <<'PY'
from pathlib import Path
import shutil

import alembic

app_alembic_dir = Path('/app/alembic')
app_template_dir = app_alembic_dir / 'templates'
app_template_dir.mkdir(parents=True, exist_ok=True)

package_template_dir = Path(alembic.__file__).resolve().parent / 'templates'

for template_file in package_template_dir.rglob('*'):
    if template_file.is_file():
        destination = app_template_dir / template_file.relative_to(package_template_dir)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(template_file, destination)

root_script_template = app_alembic_dir / 'script.py.mako'
if not root_script_template.exists():
    source = app_template_dir / 'generic' / 'script.py.mako'
    shutil.copy2(source, root_script_template)

required_template = app_alembic_dir / 'script.py.mako'
if not required_template.exists():
    raise RuntimeError(f'Missing Alembic template: {required_template}')
PY

RUN chmod +x /entrypoint.sh /app/scripts/*.sh \
    && adduser --disabled-password --gecos "" appuser \
    && chown -R appuser /app

USER appuser

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')"

ENTRYPOINT ["/entrypoint.sh"]
