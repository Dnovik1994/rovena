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
- `TELEGRAM_AUTH_TTL_SECONDS` — TTL initData (секунды). Установите `0`, чтобы отключить проверку при локальной разработке.
- `TELEGRAM_API_ID` и `TELEGRAM_API_HASH` — данные приложения Telegram (my.telegram.org).
- `SENTRY_DSN` — DSN для Sentry (опционально, если используете мониторинг).
- `STRIPE_SECRET_KEY` и `STRIPE_WEBHOOK_SECRET` — ключи Stripe для подписок.
- `VITE_TG_INIT_DATA` — initData для локального входа (если запускаете не в Telegram).
- Production: сгенерируйте сильный `JWT_SECRET` командой `openssl rand -hex 32`.

3. Запустите сервисы:

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

MySQL init script автоматически создаёт базу rovena при первом запуске.

Для режима разработки (hot-reload) можно использовать override:

```bash
docker compose -f docker-compose.yml -f docker-compose.override.yml up --build
```

4. Примените миграции:

```bash
docker compose exec backend alembic upgrade head
```

## Troubleshooting

Если получили ошибку duplicate index при миграциях, выполните:

```bash
docker compose exec backend alembic downgrade 0014
docker compose exec backend alembic upgrade head
```

## Quick Start (Production)

```bash
COMMIT_SHA=$(git rev-parse --short HEAD) docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml exec backend alembic upgrade head
```

Откройте:
- Backend healthcheck: `http://localhost/health`
- Frontend: `http://localhost/`

## Проверка

- Backend healthcheck: `http://localhost:8020/health`
- Frontend: `http://localhost:5173`

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
- First monitoring check: `curl http://localhost:9090/targets` → все targets в статусе UP.
- Grafana: `http://localhost:3000` → логин и добавление Prometheus datasource, затем проверьте дашборды.

### Server deploy commands (Ubuntu)

```bash
ssh user@server
sudo apt update && sudo apt install docker.io docker-compose-plugin git certbot python3-certbot-nginx ufw -y
sudo usermod -aG docker $USER
git clone https://github.com/your-org/rovena.git && cd rovena
cp .env.example .env && nano .env  # fill secrets
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml down -v  # first run or after old volumes
COMMIT_SHA=$(git rev-parse --short HEAD) docker compose -f docker-compose.prod.yml up -d --build
sudo certbot certonly --nginx -d kass.freecrm.biz --email your@email.com --agree-tos --non-interactive
sudo ufw allow OpenSSH && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp && sudo ufw enable
docker compose logs -f cron  # check backups
curl https://kass.freecrm.biz/health  # must 200
```

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
- Security misconfiguration: HSTS/headers в nginx, CSRF проверка (опционально).
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

## Production Checklist

- DNS указывает на сервер и порты 80/443 открыты.
- `PRODUCTION=true` и валидные secrets в `.env`.
- Certbot сертификаты и автообновление.
- Firewall: разрешены 80/443, админ IP whitelist.
- Ротация бэкапов и мониторинг `/backups`.
- UFW: `ufw allow 80` + `ufw allow 443` + `ufw allow OpenSSH`.
- Monitoring: Grafana доступна по 3000, Prometheus по 9090.

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

## Troubleshooting

- npm 403: задайте `NPM_REGISTRY` и proxy (см. раздел выше).
- Docker Hub rate limit: `docker login` перед `docker compose pull`.
