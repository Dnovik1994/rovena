# FreeCRM Inviter

Минимальный каркас проекта для Telegram Mini App и FastAPI backend.

## Быстрый старт

1. Скопируйте переменные окружения:

```bash
cp .env.example .env
```

2. Заполните `.env`:
- `TELEGRAM_BOT_TOKEN` — токен бота для проверки initData.
- `TELEGRAM_API_ID` и `TELEGRAM_API_HASH` — данные приложения Telegram (my.telegram.org).
- `SENTRY_DSN` — DSN для Sentry (опционально, если используете мониторинг).
- `STRIPE_SECRET_KEY` и `STRIPE_WEBHOOK_SECRET` — ключи Stripe для подписок.
- `VITE_TG_INIT_DATA` — initData для локального входа (если запускаете не в Telegram).

3. Запустите сервисы:

```bash
docker compose up --build
```

Для режима разработки (hot-reload) можно использовать override:

```bash
docker compose -f docker-compose.yml -f docker-compose.override.yml up --build
```

4. Примените миграции:

```bash
docker compose exec backend alembic upgrade head
```

## Проверка

- Backend healthcheck: `http://localhost:8000/health`
- Frontend: `http://localhost:5173`

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
ws://localhost:8000/ws/status?token=JWT_TOKEN
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

## Локальная авторизация

В Telegram WebApp `initData` берётся автоматически. Для локальной разработки укажите `VITE_TG_INIT_DATA` в `.env`. Это позволит пройти `/auth/telegram` и получить токен.

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

3. Примените миграции:

```bash
docker compose -f docker-compose.prod.yml exec backend alembic upgrade head
```

4. Настройте SSL сертификаты (Certbot + nginx):

```bash
certbot certonly --nginx -d kass.freecrm.biz
```

В `docker-compose.prod.yml` nginx использует volume `/etc/letsencrypt`, поэтому сертификаты автоматически доступны контейнеру nginx.

5. Проверьте доступность:

- Frontend: `https://kass.freecrm.biz/`
- Backend health: `https://kass.freecrm.biz/health`

> Для ограничения доступа к `/admin/` отредактируйте IP whitelist в `nginx.conf`.

## Monitoring

- Grafana: `http://<server>:3000` (default admin/admin)
- Prometheus: `http://<server>:9090`
- Targets: backend `/metrics`, nginx exporter, 3proxy health probe (blackbox)
- Alerts: `prometheus_rules.yml` (HighQueue, ManyBlockedAccounts)

## Load testing

```bash
locust -f locustfile.py --users 100
```
