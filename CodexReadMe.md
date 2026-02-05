# CodexReadMe — техническая документация проекта Rovena

> Актуализировано: 2026-02-05.
> Полный анализ и roadmap: [ClaudeCodeReadMe.md](ClaudeCodeReadMe.md) (основной документ).

---

## 1) Оценка готовности

Проект в стадии **pre-production (~80%)**. Все критические security-проблемы закрыты (PR #42). Все stub-эндпоинты реализованы. Dashboard, Subscription, Onboarding — рабочие. 45 тестовых файлов.

Оставшиеся задачи для production-релиза описаны в [ClaudeCodeReadMe.md, раздел 5-6](ClaudeCodeReadMe.md).

---

## 2) WebSocket reconnect — контракт и поведение

**Файл:** `frontend/src/services/websocket.ts`

### Протокол (server-side: `backend/app/main.py`)

1. Клиент открывает `ws://<origin>/ws/status`
2. Клиент отправляет first-message: `{"type":"auth","token":"<JWT>"}`
3. Сервер валидирует токен (JWT decode + проверка user.is_active в БД)
   - OK → регистрирует соединение, запускает ping loop (30 с)
   - Fail → закрывает с кодом **1008**
4. Сервер шлёт `{"type":"ping"}` каждые 30 с; клиент отвечает `"pong"`
5. Сервер пушит `StatusMessage` в любой момент

### Состояния клиента (`WsConnectionState`)

| State | Описание | Auto-retry |
|-------|----------|------------|
| `connecting` | Первая попытка подключения | — |
| `connected` | Аутентифицирован, получает данные | — |
| `disconnected` | Не подключён (initial / после dispose) | Нет |
| `reconnecting` | Потеря связи, backoff retry | Да |
| `auth_failed` | Сервер отклонил токен (code 1008) | **Нет** |

### Backoff параметры

- Base delay: **250 ms**
- Factor: **2** (exponential)
- Cap: **30 000 ms**
- Jitter: **±30%** (через `maybeJitter(ms)`)
- Формула: `min(250 * 2^attempt, 30000)` + jitter

### API

```typescript
const handle = connectStatusSocket(token, onMessage, onStateChange?);

handle.state;      // WsConnectionState
handle.attempts;   // number (reconnect attempts since last success)
handle.dispose();  // cleanup: stops timers, closes socket, no more retries
```

### Гарантии

- **Singleton**: повторный вызов `connectStatusSocket()` автоматически закрывает предыдущий
- **No duplicate timers**: `clearReconnectTimer()` перед каждым `setTimeout`
- **Safe send**: все `ws.send()` через `safeSend()` — проверяет readyState, ловит исключения
- **Safe dispose**: idempotent, noop handlers на onclose/onerror/onmessage
- **Ping watchdog**: 45 с без сообщений → force close → reconnect
- **JSON errors**: console.warn с snippet данных (до 80 символов)

### Exported test helpers

```typescript
export const computeBackoff = (attempt: number): number;
export const maybeJitter = (ms: number): number;
```

### Runbook — ручная проверка

1. **Reconnect при падении backend:**
   - Открыть Accounts/Campaigns → console: `Status WebSocket connected`
   - `docker compose stop backend`
   - Console: `[ws] Reconnect scheduled — attempt #1, delay X ms` ...
   - `docker compose start backend` → автоматический reconnect + re-auth

2. **Auth failure (1008):**
   - Протухший/невалидный JWT → console: `[ws] Auth failed (code 1008) — will not retry`
   - `handle.state === "auth_failed"`
   - Retry НЕ происходит

3. **Ping timeout:**
   - Если backend завис (не шлёт ping 45 с) → `[ws] Ping timeout ... — forcing reconnect`

4. **Singleton guard:**
   - Навигация Accounts → Campaigns: предыдущий socket закрывается, один активный

5. **Dispose (unmount):**
   - Уход со страницы → `handle.dispose()` через useEffect cleanup
   - Нет утечек таймеров/соединений

---

## 3) Health check contract

### JSON schema
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

### HTTP codes
- `ok`/`warn` → `200 OK`
- `fail` → `503 Service Unavailable`

### Runbook
```bash
curl -s http://localhost:8000/health | jq
```

---

## 4) Testing

### Backend
```bash
PYTHONPATH=backend pytest backend/tests
```

### Frontend type-check (без node_modules)
```bash
tsc --noEmit --strict --target ES2020 --module ESNext \
    --lib ES2020,DOM,DOM.Iterable \
    frontend/src/services/websocket.ts
# → Exit 0, zero errors (не требует React types)
```

### Full frontend type-check (с node_modules)
```bash
cd frontend && npx tsc --noEmit
```
