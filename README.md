# FreeCRM Inviter

Минимальный каркас проекта для Telegram Mini App и FastAPI backend.

## Быстрый старт

```bash
git clone https://github.com/your-org/rovena.git
cd rovena
```

1. Скопируйте переменные окружения:

```bash
cp .env.example .env
```

2. Заполните `.env`:
- `TELEGRAM_BOT_TOKEN` — токен бота для проверки initData.
- `TELEGRAM_AUTH_TTL_SECONDS` — TTL initData (секунды, по умолчанию 300). **Production: обязательно > 0** (защита от replay). Установите `0` только для локальной разработки.
- `TELEGRAM_API_ID` и `TELEGRAM_API_HASH` — данные приложения Telegram (my.telegram.org).
- `SENTRY_DSN` — DSN для Sentry (опционально, если используете мониторинг).
- `STRIPE_SECRET_KEY` и `STRIPE_WEBHOOK_SECRET` — ключи Stripe для подписок.
- `VITE_TG_INIT_DATA` — initData для локального входа (если запускаете не в Telegram).
- `DOMAIN` и `LE_EMAIL` — домен и email для автоматического выпуска сертификатов Traefik (Let’s Encrypt).
- Production: сгенерируйте сильный `JWT_SECRET` командой `openssl rand -hex 32`.

3. Запустите сервисы:

```bash
docker compose --env-file .env -f docker-compose.prod.yml up -d --build
```

MySQL init script автоматически создаёт базу rovena при первом запуске.

### Команды запуска (dev vs prod)

- **Dev (hot-reload):** используйте основной compose + override (только для разработки).
  ```bash
  docker compose -f docker-compose.yml -f docker-compose.override.yml up --build
  ```
- **Prod:** используйте только `docker-compose.prod.yml`, без override.
  ```bash
  docker compose --env-file .env -f docker-compose.prod.yml up -d --build
  ```

4. Примените миграции (development only — в production миграции запускаются автоматически):

```bash
docker compose exec backend alembic upgrade head
```

## Troubleshooting

Если миграции падают, проверьте логи `backend` и найдите строку
`Migration failed after retries` — после этого исправьте `0015.py` вручную.

Если базы `rovena` нет — проверьте, что `docker-entrypoint-initdb.d/init-rovena.sql`
смонтирован в контейнер.

## Quick Start (Production)

```bash
./scripts/deploy-bootstrap.sh
```

Migrations run automatically on backend startup via the safe migration runner
(advisory lock + self-heal + consistency checks). Do NOT run `alembic upgrade head`
manually in production.

> **WARNING — PRODUCTION DATA SAFETY**
>
> - **Never** run `docker compose … down -v` on production outside of `deploy-bootstrap.sh` — it destroys **all** data volumes (MySQL, Redis, Prometheus, Grafana, backups).
> - **Never** run `alembic upgrade head` manually on production — it bypasses the advisory lock and safety checks.
> - Use `./scripts/deploy-bootstrap.sh` for normal deployments.
> - Use `./scripts/deploy-bootstrap.sh --wipe-volumes` **only** for first install or explicit full wipe (requires confirmation; **destroys all data**).

### Production verification (read-only)

```bash
# Check migration status (read-only query)
docker compose -f docker-compose.prod.yml exec backend python -c \
  "from sqlalchemy import create_engine, text; from app.core.settings import get_settings; \
   e = create_engine(get_settings().database_url); c = e.connect(); \
   print('rows:', c.execute(text('SELECT COUNT(*) FROM alembic_version')).scalar()); \
   print('head:', c.execute(text('SELECT version_num FROM alembic_version')).scalar())"

# Compare with expected HEAD
docker compose -f docker-compose.prod.yml exec backend alembic heads

# Optionally trigger migrations via safe wrapper (advisory lock + checks)
docker compose -f docker-compose.prod.yml exec backend /app/scripts/run-migrations.sh
```

Откройте:
- Frontend: `https://YOUR_DOMAIN/`
- Backend healthcheck: `https://YOUR_DOMAIN/health`
  - Note: `/health` используется для readiness и Docker healthcheck.

## Проверка

- Backend healthcheck (через Traefik): `https://YOUR_DOMAIN/health`
- Frontend (через Traefik): `https://YOUR_DOMAIN/`
  - Worker containers use `service_started` on backend to avoid readiness deadlocks.

## Testing in Production

Перед реальным запуском выполните user testing checklist и зафиксируйте найденные проблемы:

- Checklist: `docs/user-testing.md`.
- Bug report template: `docs/bug-hunt.md`.
- Сообщайте о найденных ошибках через GitHub Issues и прикладывайте логи/скриншоты.

## Tests

Run tests:

```bash
PYTHONPATH=backend pytest backend/tests
```

## First Production Run

Перед первым запуском используйте deploy checklist и скрипт валидации:

- Deploy checklist: `docs/deploy-checklist.md`.
- Validation script: `scripts/validate-deploy.sh`.
- После деплоя мониторьте логи 10 минут и выполните тестовую кампанию из `docs/user-testing.md`.
- First monitoring check (из контейнера): `docker compose -f docker-compose.prod.yml exec prometheus wget -qO- http://localhost:9090/targets` → все targets в статусе UP.
- Grafana (из контейнера): `docker compose -f docker-compose.prod.yml exec grafana wget -qO- http://localhost:3000/api/health` → статус ok.

## Production deployment with Traefik

**Требования:**
- DNS A-запись `YOUR_DOMAIN` указывает на IP сервера.
- Открыты входящие порты 80/443 (и 22 для SSH).

**Подготовка:**
```bash
mkdir -p letsencrypt
touch letsencrypt/acme.json && chmod 600 letsencrypt/acme.json
cp .env.example .env
# Заполните .env (LE_EMAIL, DOMAIN, секреты)
```

**Запуск:**
```bash
docker compose -f docker-compose.prod.yml up -d --build
```

**Проверки:**
```bash
curl -I http://YOUR_DOMAIN
curl -I https://YOUR_DOMAIN/health
curl -I https://YOUR_DOMAIN/api/v1/health
```

Traefik сам выпускает и обновляет сертификаты; certbot не требуется.

### Traefik/Docker socket proxy

Traefik требует DOCKER_API_VERSION>=1.44 для Docker Engine 29.x; используем 1.44.

### Troubleshooting: Traefik Docker API incompatibility

**Симптом:** `404` на `https://127.0.0.1/` (или `https://YOUR_DOMAIN/`) и в логах Traefik есть ошибка:
`client version 1.24 is too old. Minimum supported API version is 1.44`.

**Причина:** Traefik не может обратиться к Docker API через несовместимую версию клиента, из-за чего провайдер Docker не обнаруживает роутеры.

**Исправление:** Traefik подключается к Docker API через `docker-socket-proxy` по TCP (`--providers.docker.endpoint=tcp://docker-socket-proxy:2375`). Прямой mount `docker.sock` в Traefik запрещён — доступ к сокету есть только у `docker-socket-proxy` (`:ro`). Дополнительно задаётся `DOCKER_API_VERSION=1.44` на обоих сервисах.

**Проверка после фикса (пересоздать Traefik и проверить docker provider):**
```bash
docker compose --env-file .env -f docker-compose.prod.yml config | sed -n '/^  traefik:/,/^  [A-Za-z0-9_-]\+:/p' | grep -nE 'image:|command:|providers.docker.endpoint'
docker compose --env-file .env -f docker-compose.prod.yml up -d --force-recreate --no-deps traefik docker-socket-proxy
docker compose --env-file .env -f docker-compose.prod.yml logs --tail=200 traefik | grep -F "client version 1.24 is too old" && exit 1 || true
bash scripts/verify-traefik-docker-provider.sh
```

### Troubleshooting: Traefik returns 404 on `/` (frontend not routed)

**Symptom:** `curl https://kass.freestorms.top/` returns `404 page not found` (text/plain),
while `https://kass.freestorms.top/api/v1/health` works fine.

**Cause:** Traefik has no matching router for the frontend. Common reasons:
1. **Frontend container not running** — check `docker compose ps frontend`.
2. **Old labels still cached** — if the router was renamed (e.g. `kass` → `kass-ui`),
   a `--force-recreate` is needed.
3. **Network mismatch** — frontend must be on the same Docker network as Traefik
   (`app`), and `traefik.docker.network: app` must be set in the labels.
4. **Missing `traefik.http.routers.<name>.service`** — without explicit service binding,
   Traefik may not associate the router with the loadbalancer.

**Current routing architecture (docker-compose.prod.yml):**
- `kass-api` (priority 20): `Host(…) && PathPrefix(/api/v1)` → backend:8000
- `kass-health` (priority 110): `Host(…) && Path(/health)` → backend:8000
- `kass-ws` (priority 110): `Host(…) && PathPrefix(/ws)` → backend:8000
- `kass-web` (priority 10): `Host(…)` → frontend:5173 (catch-all)

**Debug commands:**
```bash
# Check if frontend router is registered
docker compose --env-file .env -f docker-compose.prod.yml config \
  | grep -E 'kass-ui|kass-api|routers\.|services\.'

# Force recreate to pick up new labels
docker compose --env-file .env -f docker-compose.prod.yml up -d --force-recreate frontend

# Check Traefik access logs for RouterName
docker compose --env-file .env -f docker-compose.prod.yml logs --tail=200 traefik \
  | grep -E 'RouterName|kass-ui|kass-api|entryPointName'

# Verify the response
curl -fsSI https://kass.freestorms.top/ | head -20
```

## Production deploy checklist

1. Проверить конфигурацию compose:

```bash
docker compose -f docker-compose.prod.yml config
```

2. Собрать и запустить сервисы:

```bash
COMMIT_SHA=$(git rev-parse --short HEAD) docker compose -f docker-compose.prod.yml up -d --build
```

3. Проверить доступность:

```bash
curl -I https://YOUR_DOMAIN/health
curl -I https://YOUR_DOMAIN/
```

4. (Опционально) Проверить API:

```bash
curl -I https://YOUR_DOMAIN/api/v1/health
```

### Server deploy commands (Ubuntu)

```bash
ssh user@server
sudo apt update && sudo apt install docker.io docker-compose-plugin git ufw -y
sudo usermod -aG docker $USER
git clone https://github.com/your-org/rovena.git && cd rovena
cp .env.example .env && nano .env  # fill secrets
mkdir -p letsencrypt
touch letsencrypt/acme.json && chmod 600 letsencrypt/acme.json
# First install (wipes volumes — DESTROYS ALL DATA):
./scripts/deploy-bootstrap.sh --wipe-volumes
# Subsequent deploys (preserves data):
# ./scripts/deploy-bootstrap.sh
sudo ufw allow OpenSSH && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp && sudo ufw enable

# Post-deploy validation (containers, health, migrations, worker):
./scripts/validate-deploy.sh
```

> **WARNING:** Never run `docker compose -f docker-compose.prod.yml down -v` directly.
> Use `./scripts/deploy-bootstrap.sh --wipe-volumes` only for first install; it requires
> explicit confirmation and **destroys all data**.

## Traefik + Let's Encrypt (HTTP-01)

Traefik автоматически выпускает и обновляет сертификаты Let’s Encrypt через HTTP-01 challenge.
Certbot больше не используется.

Подготовка:

```bash
mkdir -p letsencrypt
touch letsencrypt/acme.json && chmod 600 letsencrypt/acme.json
```

В `.env` должны быть указаны:

- `LE_EMAIL=YOUR_EMAIL`
- `DOMAIN=YOUR_DOMAIN`

> Скрипты `scripts/certbot-init.sh` и `scripts/certbot-renew.sh` оставлены в репозитории как deprecated и больше не нужны для продакшн-деплоя.

## Security notes (production)

- Не публикуйте наружу внутренние порты (5173/8020/9090/3000/9115/10000+). Снаружи должны быть только 22/80/443, а порты мониторинга открывайте только при явной необходимости.
- API и фронт должны идти через один домен `https://YOUR_DOMAIN` и same-origin `/api/v1`.

## Log Collection & Debug

```bash
docker compose logs -f backend > backend.log
docker compose logs -f worker > worker.log
docker compose logs -f cron > cron-backup.log
docker compose exec backend tail -n 200 /app/logs/app.log
```

Grafana Explore → query `{job="backend"}` to find error spikes.

## Dev-скрипты

```bash
./scripts/dev-up.sh
./scripts/dev-check.sh
./scripts/dev-clean.sh
```

Если видите `net::ERR_EMPTY_RESPONSE`, проверьте логи фронтенда и убедитесь, что контейнер `frontend` запущен:

```bash
docker compose ps
docker logs frontend | tail -n 50
```

## Queue/Workers

Очереди и воркеры запускаются вместе с Docker Compose. При необходимости можно поднять их отдельно:

```bash
docker compose up -d redis worker
```

Настройки Celery для воркера задаются через `.env`:

- `CELERY_POOL` (по умолчанию `solo` для dev) — `solo` запускает один процесс.
- `CELERY_CONCURRENCY` (по умолчанию `1` для `solo`) — число процессов для пулов, отличных от `solo`.

## 3proxy reload

Синхронизация прокси генерирует `3proxy.cfg` и вызывает reload через SIGUSR1:

```bash
PROXY_RELOAD_CMD="docker kill --signal=USR1 3proxy"
```

Файл `3proxy.cfg` монтируется в контейнер 3proxy и перечитывается без разрыва соединений.

Проверка (после добавления/обновления прокси):

```bash
docker exec 3proxy cat /etc/3proxy/3proxy.cfg
docker logs 3proxy | tail -n 20
```

## Warming (low-risk)

Warming использует низкорисковые действия через Pyrogram: `get_me()`, `get_history()`, `get_dialogs()`, опционально `join_chat()` (публичная небольшая группа), случайные паузы 60–240 секунд. Цель — 5–15 действий в день на аккаунт.

## Device Config

При создании аккаунта автоматически генерируется `device_config` (device_model, system_version, app_version и др.). Можно пересоздать через API:

```
POST /api/v1/accounts/{id}/regenerate-device
```

## WebSocket (real-time)

Канал для статусов аккаунтов:

```
ws://localhost:8020/ws/status?token=JWT_TOKEN
```

События:

- `account_update` — изменение статуса/прогресса прогрева.
- `campaign_progress` — прогресс кампании (будет расширяться).
- `dispatch_error` — ошибки инвайтинга по кампании.

## Admin API

Админ-метрики доступны по:

```
GET /api/v1/admin/stats
```

## Metrics

Prometheus endpoint:

```
GET /metrics
```

## MVP Usage Guide

1. **Create a project**
   - Go to Projects → Create.
   - Provide a short name and optional description.
2. **Add a proxy**
   - Go to Admin → Proxies → Create.
   - Validate the proxy to confirm connectivity.
3. **Add an account**
   - Go to Accounts → Create.
   - Attach proxy if required.
4. **Verify account**
   - Use the verification flow and enter the phone code if prompted.
5. **Start warming**
   - Trigger warming to generate low-risk activity.
6. **Create a campaign**
   - Configure source/target and invite limits.
7. **Start campaign**
   - Click Start; monitor progress in Campaigns.

## Load Test

Быстрый запуск Locust (пример):

```bash
locust -f locustfile.py -u 100 -r 10 --headless -t 10m --host http://localhost
```

Для сценариев используйте переменные окружения:

- `LOCUST_INIT_DATA` — initData для `/auth/telegram`
- `LOCUST_CAMPAIGN_ID` — ID кампании для `/campaigns/{id}/start`
- `LOCUST_ADMIN_TOKEN` — токен администратора для `/admin/stats`

Шаблон отчёта: `docs/load_test.md`.

## Security Audit (OWASP basics)

- Broken authentication: JWT access tokens (15 min) + refresh tokens (rotation) and server-side storage.
- Injection: входные данные проходят Pydantic-валидацию/экранирование, SQL-инъекции отклоняются.
- XSS: CSP + X-Content-Type-Options + X-XSS-Protection.
- Security misconfiguration: HSTS/headers в Traefik или приложении, CSRF проверка (опционально).
- Sensitive data exposure: refresh token хранится хэшированным.
- Access control: IP whitelist на `/admin/` и RBAC на API.

## Обход блокировок PyPI / npm в Украине

Если доступ к PyPI или npm ограничен, можно задать альтернативные registry и прокси.

### PyPI

```bash
export PIP_INDEX_URL=https://pypi.org/simple
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r backend/requirements.txt
```

### npm

В `.env`:

```bash
NPM_REGISTRY=https://registry.npmjs.org/
```

### Proxy

```bash
HTTP_PROXY=http://proxy:8080
HTTPS_PROXY=http://proxy:8080
NO_PROXY=localhost,127.0.0.1,*.local
```

Эти переменные будут прокинуты в backend/frontend/worker через Docker Compose.

## Как правильно открыть Mini App (initData)

### Почему `Telegram` undefined в обычном браузере

Объект `window.Telegram.WebApp` создаётся Telegram-клиентом при запуске Mini App.
Если открыть URL приложения (`https://kass.freestorms.top/`) напрямую в Chrome/Safari/Firefox,
Telegram SDK загрузится (через `<script>` в `index.html`), но `initData` будет пустой строкой,
потому что браузер не предоставляет подпись пользователя — это делает только клиент Telegram.

### Как открыть правильно

1. **Через Menu Button бота** — зайдите в чат с ботом `@freeinviters_bot` → нажмите кнопку «Menu» (слева от поля ввода).
2. **Через Inline Button** — бот отправляет сообщение с кнопкой типа `web_app`, нажмите на неё.
3. **Через BotFather** — откройте `@BotFather` → `/mybots` → выберите бота `@freeinviters_bot` → Bot Settings → Menu Button → укажите URL приложения (`https://kass.freestorms.top/`).

Во всех случаях Telegram откроет встроенный WebView и передаст `initData` с подписью.

### Требования к кнопкам бота (WebApp launch)

Все кнопки, открывающие Mini App, должны быть **WebApp-кнопками**, а не обычными URL:

- `InlineKeyboardButton` с полем `web_app`.
- `ReplyKeyboardButton` с полем `web_app`.
- `setChatMenuButton` с `type="web_app"`.

URL должен совпадать с доменом, указанным в настройках WebApp для бота (BotFather → Web App).
Обычные `url`-кнопки откроют браузер и дадут пустой `initData`.

### Smoke-check в консоли Mini App

Откройте Mini App внутри Telegram и выполните в консоли:

```js
typeof window.Telegram
window.Telegram.WebApp.version
window.Telegram.WebApp.initData.length
```

Ожидаемые значения при корректном запуске:

- `typeof window.Telegram` → `"object"`
- `window.Telegram.WebApp.version` → строка версии SDK (например, `"6.9"`)
- `window.Telegram.WebApp.initData.length` → `> 0`

Если открыть URL напрямую в браузере, `window.Telegram` будет `undefined` или `initData.length` будет `0`.

### Debug-панель в UI

Для диагностики можно включить debug-панель:

- В development: доступна автоматически.
- В production: добавьте `?debug=1` к URL (например, `https://kass.freestorms.top/?debug=1`).

Debug-панель показывает user agent, текущий URL, флаг `isTelegramWebApp`, длину `initData`,
количество ключей `initDataUnsafe`, а также `user id`, `auth_date`, `query_id`.

### Проверка backend валидации initData

Backend проверяет подпись `initData` и отклоняет запросы без валидной подписи. Пример команды:

```bash
curl -X POST http://localhost:8000/api/v1/auth/telegram \\
  -H "Content-Type: application/json" \\
  -d '{"init_data":"<PASTE_INIT_DATA_HERE>"}'
```

Ответ `200` с токенами означает успешную валидацию; `401`/`422` — неверный или отсутствующий initData.

### Короткий checklist проверки

- Открыть Mini App через Menu Button бота → debug-панель показывает `isTelegramWebApp=true`, `initData length > 0`.
- Вызвать `POST /api/v1/auth/telegram` с `initData` → получить `200` и токены.
- Открыть URL в браузере → увидеть сообщение «Open this app from Telegram...».

### Локальная разработка (без Telegram)

Для локальной разработки, когда `window.Telegram.WebApp` недоступен, задайте переменную окружения:

```bash
VITE_TG_INIT_DATA="query_id=...&user=...&auth_date=...&hash=..."
```

Эта переменная используется **только** как fallback, когда Telegram WebApp не обнаружен.

### Диагностика проблем

| Симптом | Причина | Решение |
|---|---|---|
| «Telegram WebApp не обнаружен» | Открыто в обычном браузере | Откройте через Telegram-бот |
| «initData пуст» | URL открыт в Telegram, но не как Mini App | Используйте Menu Button или Inline Button бота |
| `ReferenceError: Telegram` | Код обращается к `Telegram` без проверки | Обновите код — используйте `window.Telegram?.WebApp` |

## npm registry blocked (403)

Если Docker-сборка фронтенда падает на `npm install` из-за блокировок, можно переопределить registry:

```bash
NPM_REGISTRY=https://registry.npmjs.org/
```

Или задать прокси-переменные:

```bash
HTTP_PROXY=http://proxy:8080
HTTPS_PROXY=http://proxy:8080
NO_PROXY=localhost,127.0.0.1
```

Добавьте их в `.env` и перезапустите `docker compose up --build`.

## Deployment to Server

1. Получите изменения и обновите переменные окружения:

```bash
git pull
cp .env.example .env
```

2. Запустите production stack:

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

3. Миграции выполняются автоматически при запуске backend.
   Не запускайте `alembic upgrade head` вручную на production — это обходит advisory lock и проверки безопасности.
   Для ручного запуска через безопасный wrapper:

```bash
docker compose -f docker-compose.prod.yml exec backend /app/scripts/run-migrations.sh
```

4. Подготовьте хранилище сертификатов для Traefik:

```bash
mkdir -p letsencrypt
touch letsencrypt/acme.json && chmod 600 letsencrypt/acme.json
```

## Production Checklist

### Обязательные env-переменные для production

| Переменная | Требование |
|---|---|
| `PRODUCTION` | `true` |
| `JWT_SECRET` | Сильный секрет (`openssl rand -hex 32`) |
| `DATABASE_URL` | Не дефолтный |
| `TELEGRAM_BOT_TOKEN` | Токен бота |
| `TELEGRAM_AUTH_TTL_SECONDS` | > 0 (рекомендуется 300) |
| `CORS_ORIGINS` | JSON-список реальных доменов |

- DNS указывает на сервер и порты 80/443 открыты.
- `PRODUCTION=true` и валидные secrets в `.env`.
- Traefik выпускает и обновляет сертификаты Let's Encrypt автоматически.
- Firewall: разрешены 80/443, админ IP whitelist.
- Ротация бэкапов и мониторинг `/backups`.
- UFW: `ufw allow 80` + `ufw allow 443` + `ufw allow OpenSSH`.
- Monitoring: Grafana доступна по 3000, Prometheus по 9090.

Traefik использует `./letsencrypt/acme.json` для хранения сертификатов.

5. Проверьте доступность:

- Frontend: `https://YOUR_DOMAIN/`
- Backend health: `https://YOUR_DOMAIN/health`

> Для ограничения доступа к `/admin/` используйте middleware на стороне Traefik или правила на уровне сети.

## Monitoring

- Grafana: `http://<server>:3000` (default admin/admin)
- Prometheus: `http://<server>:9090`
- Targets: backend `/metrics`, 3proxy health probe (blackbox)
- Alerts: `prometheus_rules.yml` (HighQueue, ManyBlockedAccounts)

## Load testing

```bash
locust -f locustfile.py --users 100
```

## Backups

- Backups сохраняются в volume `/backups`.
- Расписание: ежедневно в 03:00 (MySQL dump) и 04:00 (Redis dump).
- Retention: 7 дней (cleanup через `find -mtime +7`).

Восстановление:

```bash
gunzip /backups/db-YYYYMMDD.sql.gz
mysql -h db -u$MYSQL_USER -p$MYSQL_PASSWORD $MYSQL_DATABASE < /backups/db-YYYYMMDD.sql
gunzip /backups/redis-YYYYMMDD.rdb.gz
redis-cli -u $REDIS_URL --rdb /backups/redis-YYYYMMDD.rdb
```

## Roadmap

Подробный анализ проекта и план доработок: [ClaudeCodeReadMe.md](ClaudeCodeReadMe.md).

### Текущий статус: Pre-production (~80%)

Все критические security-проблемы закрыты. Все страницы и API-эндпоинты реализованы. 45 тестовых файлов.

### Что осталось до production

**Phase 1 — Frontend Hardening (DONE):**
- [x] WebSocket reconnection с exponential backoff + jitter
- [x] React Error Boundary (global)
- [x] API fetch timeouts (AbortController)

**Phase 2 — Infrastructure Hardening:**
- [ ] Пиннинг Docker-образов (traefik, prometheus, grafana, blackbox)
- [ ] Docker network isolation (3 сети)
- [ ] Resource limits (CPU/memory) на контейнеры
- [x] Docker socket proxy для Traefik

**Phase 3 — Monitoring & Reliability:**
- [ ] MySQL/Redis Prometheus exporters
- [ ] Расширенные alerting rules
- [ ] Backup verification (checksums)
- [ ] Database locking для campaign dispatch

## Troubleshooting

- npm 403: задайте `NPM_REGISTRY` и proxy (см. раздел выше).
- Docker Hub rate limit: `docker login` перед `docker compose pull`.
