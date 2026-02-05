# CodexReadMe — оценка готовности проекта Rovena

> Ручная проверка кода и сопоставление с ClaudeCodeReadMe.

## 1) Общая оценка готовности

Проект выглядит как **поздний MVP**: ядро функционала присутствует, но заметны незавершённые элементы пользовательского интерфейса и отдельные заглушки/упрощения в бэкэнде. Основа для запуска и пилотного использования есть, однако перед продакшеном нужно закрыть блоки безопасности, устойчивости и полноты UX. Для ориентира я бы оценил готовность на **~60–70%**, с перекосом в пользу бэкэнда.

## 2) Что сделано

- **Базовая структура full‑stack присутствует**: выделены backend/app с API, services, workers и frontend/src с pages и services. Это подтверждает полноценную архитектуру, описанную в ClaudeCodeReadMe. 【F:ClaudeCodeReadMe.md†L61-L109】
- **Прокси‑валидация реализована не как заглушка** — эндпоинт `/proxies/validate` реально пытается установить TCP‑соединение и возвращает результат. 【F:backend/app/api/v1/proxies.py†L72-L118】
- **Перезагрузка 3proxy уже без shell‑инъекции**: используется `shlex.split()` и `shell=False`, в отличие от старого утверждения в ClaudeCodeReadMe. 【F:backend/app/services/proxy_sync.py†L43-L54】
- **Dashboard analytics v1** — добавлены метрики, последние кампании и спарклайны по аккаунтам/кампаниям. 【F:frontend/src/pages/Dashboard.tsx†L1-L255】
- **Hardened /health** — единый контракт, non‑blocking I/O, timeout-ошибки и корректные HTTP‑коды. 【F:backend/app/main.py†L237-L316】
- **Prod guards** — проверка критичных секретов/конфигов при production запуске. 【F:backend/app/core/settings.py†L70-L89】

## 3) Что не готово / требует доработки

- **Dashboard analytics v2** — требуется расширить метрики (успех/ошибки инвайтов, конверсии, ретеншн) и добавить детализацию по кампаниям. 【F:frontend/src/pages/Dashboard.tsx†L1-L255】
- **Feature flags для prod guards** — часть проверок можно сделать конфигурируемыми для гибких деплоев. 【F:backend/app/core/settings.py†L70-L89】
- **WebSocket token hardening** — рассмотреть передачу токена через subprotocol или одноразовые токены. 【F:frontend/src/services/websocket.ts†L1-L53】

## 4) Проблемы/риски, которые стоит учесть

- **Секреты и дефолты**: в настройках присутствуют дефолтные значения для БД и JWT (`jwt_secret = "change-me"`), что требует обязательного переопределения в продакшене. 【F:backend/app/core/settings.py†L18-L39】
- **Ограничения по готовности UX**: ключевые страницы (например, Dashboard) не дают пользователю реальной аналитики/состояния — это снижает ценность продукта на старте. 【F:frontend/src/pages/Dashboard.tsx†L1-L20】

## 5) Сопоставление с ClaudeCodeReadMe

Ниже кратко — что из отчёта Claude совпадает, а что уже отличается:

### Совпадает
- **Dashboard как placeholder** — действительно пустой. 【F:ClaudeCodeReadMe.md†L146-L152】【F:frontend/src/pages/Dashboard.tsx†L1-L20】
- **Account health check как заглушка** — подтверждено. 【F:ClaudeCodeReadMe.md†L152-L155】【F:backend/app/workers/tasks.py†L262-L269】
- **WebSocket токен в URL** — подтверждено. 【F:ClaudeCodeReadMe.md†L214-L220】【F:frontend/src/services/websocket.ts†L17-L23】

### Не совпадает / устарело
- **Proxy validation**: в ClaudeCodeReadMe написано, что эндпоинт возвращает hardcoded `{"valid": true}`. В текущем коде выполняется реальная TCP‑проверка. 【F:ClaudeCodeReadMe.md†L149-L151】【F:backend/app/api/v1/proxies.py†L90-L118】
- **proxy_sync shell‑инъекция**: в актуальной версии используется `shell=False`, поэтому риск снижен. 【F:ClaudeCodeReadMe.md†L176-L183】【F:backend/app/services/proxy_sync.py†L43-L54】

## 6) Итог

Проект технически неплохо структурирован и уже работает как MVP, но есть видимые пробелы в UI/UX и в части операционных/безопасностных аспектов. Приоритетные шаги: довести основные страницы (Dashboard/Subscription/Onboarding), закрыть заглушки в фоне (health check), укрепить безопасную передачу токенов и пересмотреть секреты/конфигурации для production.

## 7) Health check contract

### JSON schema (пример)
```json
{
  "status": "ok",
  "checks": {
    "database": { "status": "ok", "latency_ms": 12 },
    "redis": { "status": "warn", "detail": "disabled" },
    "celery_queue": { "status": "warn", "detail": "disabled" },
    "celery_worker": { "status": "warn", "detail": "disabled" }
  },
  "timestamp": "2026-02-05T18:30:00+00:00",
  "version": "1.0.0"
}
```

### Правила HTTP-кодов
- `ok`/`warn` → `200 OK`
- `fail` → `503 Service Unavailable`

### Checks
- `database`: результат `SELECT 1` + `latency_ms`
- `redis`: `ping()` или `warn` если отключён
- `celery_queue`: длина очереди `celery`
- `celery_worker`: количество ответивших воркеров на `celery_app.control.ping()`

### Настройки
- `health_check_timeout_seconds` — общий таймаут (сек)
- `health_queue_warn_threshold` — порог предупреждения по длине очереди

### Runbook
```bash
curl -s http://localhost:8000/health | jq
```

## 8) Testing

### Зависимости
- `pytest`
- `httpx`

### Команды
```bash
pytest backend/tests/test_api.py backend/tests/test_analytics.py
```

## 9) Feature flags

Backend (env, boolean):
- `STRIPE_ENABLED` — включает Stripe webhook и admin checkout (при `false` endpoints возвращают 501). 【F:backend/app/main.py†L359-L374】【F:backend/app/api/v1/admin.py†L322-L338】
- `SENTRY_ENABLED` — включает инициализацию Sentry (только если задан DSN). 【F:backend/app/main.py†L47-L52】
- `TELEGRAM_AUTH_ENABLED` — включает `/auth/telegram` и валидацию initData. 【F:backend/app/api/v1/auth.py†L24-L39】【F:backend/app/services/telegram_auth.py†L19-L39】
- `TELEGRAM_CLIENT_ENABLED` — включает Pyrogram‑клиенты (аккаунты, warming, proxy validation). 【F:backend/app/clients/telegram_client.py†L30-L74】【F:backend/app/workers/tasks.py†L115-L352】
- `CSRF_ENABLED` — включает проверку `X-CSRF-Token` для mutating запросов. 【F:backend/app/api/deps.py†L64-L71】

Defaults:
- `TELEGRAM_AUTH_ENABLED=true` (логин через Telegram WebApp — основной вход в продукт).
- Все остальные flags по умолчанию `false`. 【F:backend/app/core/settings.py†L27-L47】

## 10) Production config validation

Always required in prod:
- `JWT_SECRET` не дефолтный.
- `DATABASE_URL` не дефолтный.
- `CORS_ORIGINS` не пустой и не `["*"]`. 【F:backend/app/core/settings.py†L70-L90】

Conditional (только при включённых фичах):
- `STRIPE_ENABLED=true` → `STRIPE_SECRET_KEY` и `STRIPE_WEBHOOK_SECRET` обязательны.
- `TELEGRAM_AUTH_ENABLED=true` → `TELEGRAM_BOT_TOKEN` обязателен.
- `TELEGRAM_CLIENT_ENABLED=true` → `TELEGRAM_API_ID` и `TELEGRAM_API_HASH` обязательны.
- `CSRF_ENABLED=true` → `CSRF_TOKEN` обязателен.
- `SENTRY_ENABLED=true` → `SENTRY_DSN` обязателен. 【F:backend/app/core/settings.py†L70-L90】
