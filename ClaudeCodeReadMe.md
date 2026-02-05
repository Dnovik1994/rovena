# ClaudeCodeReadMe - Анализ проекта Rovena (FreeCRM Inviter)

> Актуализировано: 2026-02-05 | На основе PR #32-#43

---

## 1. Общее описание проекта

**Rovena (FreeCRM Inviter)** - полнофункциональная платформа для автоматизации массовых приглашений пользователей в Telegram-группы и каналы. Реализована как **Telegram Mini App** (WebApp) с полным стеком: FastAPI backend, React frontend, Docker-инфраструктура с мониторингом.

### Основная бизнес-логика

1. **Управление Telegram-аккаунтами** - подключение, верификация (2FA), прогрев (warming), генерация конфигурации устройств
2. **Система кампаний** - массовые инвайт-кампании из source-групп в target-группы с контролем лимитов (в час/день)
3. **Управление контактами** - формирование списков контактов, тегирование, блокировка
4. **Прокси-сервер** - поддержка HTTP, SOCKS5, residential-прокси для ротации аккаунтов
5. **Тарифная система** - подписки через Stripe с лимитами по количеству аккаунтов и инвайтов
6. **Онбординг** - пошаговый 3-step wizard для новых пользователей

---

## 2. Технологический стек

### Backend
| Технология | Версия | Назначение |
|---|---|---|
| Python | 3.12 | Язык бэкенда |
| FastAPI | 0.115.5 | Web-фреймворк (async) |
| SQLAlchemy | 2.0.35 | ORM |
| Alembic | 1.13.2 | Миграции БД |
| MySQL | 8.4 | Основная БД |
| Redis | 7 | Кэш + брокер Celery |
| Celery | 5.4.0 | Фоновые задачи |
| Pyrogram | 2.0.106 | Telegram MTProto клиент |
| Stripe | 10.9.0 | Платёжная система |
| Uvicorn | 0.30.6 | ASGI-сервер |
| Sentry SDK | 2.17.0 | Мониторинг ошибок |
| structlog | 24.4.0 | Структурированное логирование |
| prometheus-client | 0.20.0 | Метрики |
| SlowAPI | - | Rate limiting |

### Frontend
| Технология | Версия | Назначение |
|---|---|---|
| React | 18.3.1 | UI-фреймворк |
| TypeScript | 5.6.3 | Типизация |
| Vite | 5.4.8 | Сборщик |
| Zustand | 4.5.5 | State management |
| TanStack React Query | 5.59.0 | Кэширование запросов |
| React Hook Form | 7.53.0 | Формы |
| Zod | - | Валидация |
| Tailwind CSS | 3.4.13 | Стили |

### Инфраструктура
| Технология | Назначение |
|---|---|
| Docker & Docker Compose | Контейнеризация |
| Traefik 3 | Reverse proxy + HTTPS (Let's Encrypt) |
| Nginx | Продакшн-сервер фронтенда |
| Prometheus | Сбор метрик |
| Grafana | Визуализация |
| Blackbox Exporter | HTTP/TCP-пробы |
| 3proxy | Прокси-сервер для аккаунтов |
| GitHub Actions | CI/CD (build + deploy) |

---

## 3. Архитектура проекта

```
rovena/
├── backend/                    # FastAPI backend (Python 3.12)
│   ├── app/
│   │   ├── api/v1/             # REST API endpoints (9 модулей)
│   │   ├── models/             # SQLAlchemy модели (11 таблиц)
│   │   ├── schemas/            # Pydantic-схемы + SanitizedModel
│   │   ├── services/           # Бизнес-логика (proxy_sync, websocket)
│   │   ├── clients/            # Внешние интеграции (Telegram)
│   │   ├── core/               # Ядро (settings, auth, cache, RBAC)
│   │   ├── workers/            # Celery-задачи
│   │   └── utils/              # Утилиты
│   ├── alembic/                # Миграции БД
│   ├── tests/                  # 45 тестовых файлов
│   └── Dockerfile
├── frontend/                   # React SPA (TypeScript)
│   ├── src/
│   │   ├── pages/              # 13 страниц
│   │   ├── components/         # 6 переиспользуемых компонентов
│   │   ├── services/           # API + WebSocket клиенты
│   │   ├── stores/             # Zustand-сторы
│   │   └── types/              # 9 TypeScript-интерфейсов
│   ├── Dockerfile / Dockerfile.dev
│   └── nginx.conf
├── proxy/                      # 3proxy контейнер
├── docs/                       # Документация
├── .github/workflows/          # CI/CD пайплайны
├── docker-compose.yml          # Dev-стек
├── docker-compose.prod.yml     # Prod-стек (11 сервисов)
├── prometheus.yml              # Мониторинг
├── locustfile.py               # Нагрузочное тестирование
└── Makefile                    # Dev-команды
```

### Схема базы данных

- **users** - пользователи (telegram_id, role, tariff_id, onboarding)
- **accounts** - Telegram-аккаунты (phone, status, proxy_id, device_config, warming)
- **projects** - проекты пользователя
- **sources** - source-группы/каналы для парсинга контактов
- **targets** - target-группы/каналы для приглашений
- **contacts** - список контактов (telegram_id, tags, blocked)
- **campaigns** - кампании инвайтинга (status, limits, progress)
- **campaign_dispatch_log** - лог ошибок рассылки
- **proxies** - прокси-серверы (host, port, type, status, latency)
- **tariffs** - тарифные планы (limits, price)
- **refresh_tokens** - токены обновления (hashed)

### API Endpoints (/api/v1)

| Группа | Endpoints | Описание |
|---|---|---|
| Auth | POST /auth/telegram, POST /auth/refresh | Аутентификация через Telegram initData |
| Users | GET/PATCH /me | Профиль пользователя |
| Projects | CRUD /projects | Управление проектами |
| Accounts | CRUD /accounts + verify, warm, regenerate-device | Управление Telegram-аккаунтами |
| Campaigns | CRUD /campaigns + start/pause/stop | Управление кампаниями |
| Contacts | CRUD /contacts | Управление контактами |
| Sources | CRUD /sources | Управление source-группами |
| Targets | CRUD /targets | Управление target-группами |
| Proxies | CRUD /admin/proxies + validate | Управление прокси (admin) |
| Admin | GET /admin/stats | Статистика системы |
| WebSocket | WS /ws/status | Real-time обновления |
| Stripe | POST /webhook/stripe | Вебхук платежей |
| Health | GET /health, /version, /metrics | Мониторинг |

---

## 4. Прогресс: что сделано после первого аудита

### PR #42: Security & Validation Fixes
- Shell injection fix: `shlex.split()` + `shell=False` в proxy_sync.py
- JWT int parsing: try-catch обёртки в WebSocket и Stripe handlers
- setattr whitelist: явные `_*_UPDATE_FIELDS` в accounts, proxies, admin
- WebSocket токен перенесён из URL query в первое сообщение (auth message)
- Rate limiting через SlowAPI на все endpoints (10/min auth, 5/min actions)
- Pagination (limit/offset) на все list-эндпоинты
- Input sanitization через SanitizedModel
- CSRF-проверка (опционально, через настройку)
- Production startup validation: отклоняет дефолтные credentials

### PR #41: Project Analysis
- Создан ClaudeCodeReadMe.md с полным аудитом проекта

### PR #32-#40: Infrastructure Fixes
- 3proxy: исправлен config mount, healthcheck, init script, daemon mode, build
- Traefik: Docker provider endpoint, API version compatibility
- Cron: правильный image для production
- Volume naming: postgres-data -> mysql-data
- Production ENV и .env.example

### Ранее реализованный функционал
- Dashboard — полноценная страница с аналитикой, графиками, статистикой
- Proxy validation — реальная TCP-проверка (socket connect, 5s timeout)
- Account health check — async проверка через Pyrogram get_me()
- CI/CD — полный deploy.yml (build images + SSH deploy на сервер)
- Subscription/Stripe — страница тарифов с checkout session creation
- Onboarding — 3-step wizard (proxy → account → campaign)
- Campaign validation — Pydantic схемы с min/max, sanitization
- 45 тестовых файлов (security, performance, backup, migrations, etc.)

---

## 5. Оставшиеся проблемы и задачи

### 5.1 High Priority

#### 5.1.1 WebSocket reconnection отсутствует
**Файл:** `frontend/src/services/websocket.ts`
При закрытии соединения (потеря сети, перезапуск сервера) нет автоматического переподключения. Есть ping/pong, но нет retry.

**Как реализовать:**
- Добавить reconnection с exponential backoff (1s, 2s, 4s, 8s, max 30s)
- Максимум попыток: 10, затем показать пользователю ошибку
- При успешном reconnect — повторно отправить auth message
- Добавить состояние соединения (connecting/connected/disconnected) в UI

```typescript
// Псевдокод
let reconnectAttempts = 0;
const MAX_RECONNECT = 10;

function connect() {
  const socket = new WebSocket(url);
  socket.onclose = () => {
    if (reconnectAttempts < MAX_RECONNECT) {
      const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 30000);
      setTimeout(connect, delay);
      reconnectAttempts++;
    }
  };
  socket.onopen = () => {
    reconnectAttempts = 0;
    socket.send(JSON.stringify({ type: "auth", token }));
  };
}
```

#### 5.1.2 React Error Boundary отсутствует
**Файлы для создания:** `frontend/src/components/ErrorBoundary.tsx`
Ошибка рендеринга в любом компоненте крашит всё приложение. Есть `ErrorState` и `ErrorPage`, но нет class-based Error Boundary.

**Как реализовать:**
- Создать class component с `componentDidCatch` и `getDerivedStateFromError`
- Обернуть `<App />` в `<ErrorBoundary>` в main.tsx
- Показывать fallback UI с кнопкой "Перезагрузить"
- Интегрировать с Sentry для отправки ошибок

```tsx
class ErrorBoundary extends React.Component<Props, State> {
  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }
  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    // Sentry.captureException(error, { extra: errorInfo });
  }
  render() {
    if (this.state.hasError) return <ErrorFallback onRetry={() => this.setState({ hasError: false })} />;
    return this.props.children;
  }
}
```

#### 5.1.3 Нет таймаутов на API-запросы фронтенда
**Файл:** `frontend/src/services/api.ts`
Fetch-запросы могут зависнуть навсегда. Нет AbortController.

**Как реализовать:**
- Обернуть все fetch-вызовы в `apiFetch()` с AbortController
- Дефолтный timeout: 15s для обычных запросов, 30s для загрузки файлов
- Показывать пользователю ошибку при timeout

```typescript
async function apiFetch(url: string, options: RequestInit = {}, timeoutMs = 15000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    return response;
  } finally {
    clearTimeout(timer);
  }
}
```

#### 5.1.4 Пиннинг Docker-образов (частично)
**Файл:** `docker-compose.prod.yml`
4 образа используют `:latest`:
- `traefik:latest` → пиннить на `traefik:v3.1`
- `prom/prometheus:latest` → пиннить на `prom/prometheus:v2.51.0`
- `grafana/grafana:latest` → пиннить на `grafana/grafana:10.4.0`
- `prom/blackbox-exporter:latest` → пиннить на `prom/blackbox-exporter:v0.25.0`

---

### 5.2 Medium Priority

#### 5.2.1 Docker socket в production
**Файл:** `docker-compose.prod.yml:34`
```yaml
- /var/run/docker.sock:/var/run/docker.sock:ro
```
Read-only доступ к Docker socket всё ещё позволяет просматривать env-переменные всех контейнеров.

**Как решить:**
- Вариант А: Использовать Traefik с файловым провайдером вместо Docker провайдера (не нужен socket)
- Вариант Б: Использовать [docker-socket-proxy](https://github.com/Tecnativa/docker-socket-proxy) для фильтрации API-вызовов
- Вариант В (минимум): Оставить как есть, но задокументировать риск

#### 5.2.2 Нет сетевой изоляции Docker
Все 11 сервисов в одной default-сети. Frontend может обращаться к MySQL напрямую.

**Как реализовать:**
- Создать 3 сети: `frontend-net`, `backend-net`, `db-net`
- frontend + traefik → `frontend-net`
- backend + worker + redis + db → `backend-net`
- db + redis → `db-net` (только для бэкенда)
- traefik → обе сети (для проксирования)

#### 5.2.3 Нет лимитов ресурсов (CPU/Memory)
Ни один сервис не имеет `deploy.resources.limits`.

**Как реализовать (рекомендуемые лимиты):**
```yaml
services:
  backend:
    deploy:
      resources:
        limits: { cpus: "1.0", memory: "512M" }
  worker:
    deploy:
      resources:
        limits: { cpus: "1.0", memory: "1G" }
  db:
    deploy:
      resources:
        limits: { cpus: "1.0", memory: "1G" }
  redis:
    deploy:
      resources:
        limits: { cpus: "0.5", memory: "256M" }
  frontend:
    deploy:
      resources:
        limits: { cpus: "0.5", memory: "256M" }
```

#### 5.2.4 Мониторинг — нет экспортёров MySQL/Redis
Prometheus скрейпит только backend `/metrics` и blackbox TCP-пробу.

**Как реализовать:**
- Добавить `mysqld-exporter` (image: `prom/mysqld-exporter:v0.15.1`) — скрейпит MySQL метрики
- Добавить `redis-exporter` (image: `oliver006/redis_exporter:v1.58.0`) — скрейпит Redis метрики
- Добавить scrape jobs в `prometheus.yml`
- Добавить alerting rules: DiskSpaceHigh, HighMemory, ServiceDown, MySQLSlowQueries, RedisHighMemory

#### 5.2.5 Race condition в dispatch кампаний
**Файл:** `backend/app/workers/tasks.py`
Статус кампании/аккаунта может измениться между проверкой и обработкой. Нет `SELECT FOR UPDATE`.

**Как реализовать:**
- Использовать `with_for_update()` при выборке кампании перед изменением статуса
- Обернуть критические секции в явные транзакции
- Добавить optimistic locking (version column) на модель Campaign

#### 5.2.6 Бэкапы без верификации
**Файл:** `crontab.txt`
Нет проверки успешности mysqldump, нет checksums.

**Как реализовать:**
- После dump: `md5sum /backups/db-*.sql.gz > /backups/db-*.md5`
- Проверять exit code mysqldump: `mysqldump ... && gzip ... || echo "BACKUP FAILED" >> /backups/backup.log`
- Добавить Prometheus-метрику `backup_last_success_timestamp`

---

### 5.3 Low Priority

#### 5.3.1 Accessibility (a11y)
- Toast: добавить `role="alert"` и `aria-live="polite"`
- Формы: добавить `htmlFor` на `<label>` и `aria-labelledby`
- Статусы: добавить текстовые badge рядом с цветовыми индикаторами
- Loading: `aria-busy="true"` на скелетоны

#### 5.3.2 Hardcoded credentials (dev-окружение)
Dev-значения остаются в docker-compose.yml и init-rovena.sql. Production защищён через startup validation в settings.py. Для полной чистоты — вынести все dev-credentials в .env.example и убрать из кода.

#### 5.3.3 WebSocket Manager broadcast_sync
**Файл:** `backend/app/services/websocket_manager.py`
`asyncio.run()` в broadcast_sync создаёт новый event loop каждый раз. Неэффективно, но не критично при малом числе соединений.

---

## 6. Roadmap до production

### Phase 1: Frontend Hardening (2-3 дня)
1. WebSocket reconnection с exponential backoff
2. React Error Boundary
3. API fetch timeouts через AbortController
4. A11y базовые исправления (role, aria)

### Phase 2: Infrastructure Hardening (1-2 дня)
5. Пиннинг Docker-образов
6. Docker network isolation (3 сети)
7. Resource limits на все контейнеры
8. Docker socket proxy или file provider для Traefik

### Phase 3: Monitoring & Reliability (2-3 дня)
9. MySQL/Redis экспортёры в Prometheus
10. Расширенные alerting rules (5+ правил)
11. Backup verification (checksums, exit codes)
12. Database locking для campaign dispatch

### Phase 4: Nice-to-have (опционально)
13. Аналитика кампаний — графики конверсии, success/blocked rate
14. Шедулинг кампаний — запуск по расписанию
15. Импорт/экспорт контактов (CSV/Excel)
16. Telegram Bot уведомления о статусе кампаний
17. Account Pool Rotation при блокировке

---

## 7. Оценка зрелости проекта (обновлённая)

| Аспект | Статус | Оценка |
|---|---|---|
| Backend API | Готов (rate limit, pagination, validation) | 92% |
| Frontend UI | Все страницы реализованы | 82% |
| Аутентификация | Реализована + CSRF + sanitization | 95% |
| Telegram-интеграция | Работает (verify, warming, health check) | 85% |
| Платежи (Stripe) | Полная страница + webhook | 75% |
| Мониторинг | Базовый (нет MySQL/Redis exporters) | 50% |
| CI/CD | Build + Deploy настроен | 70% |
| Тестирование | 45 тестовых файлов | 70% |
| Документация | README + ClaudeCodeReadMe + docs/ | 80% |
| Безопасность | Критические закрыты, остался socket | 80% |
| DevOps/Infra | Docker настроен, нет network isolation | 72% |
| **Общая оценка** | **Pre-production** | **~80%** |

### Вывод

Проект перешёл из стадии "поздний MVP" в **pre-production**. Все критические security-проблемы закрыты (PR #42). Все stub-эндпоинты реализованы. Dashboard, Subscription, Onboarding — полностью рабочие. 45 тестовых файлов обеспечивают хорошее покрытие. Для production-релиза остаётся: frontend hardening (WebSocket reconnect, Error Boundary, timeouts), infrastructure hardening (network isolation, resource limits, image pinning) и расширение мониторинга.

---

*Актуализировано на основе анализа PR #32-#43 и текущего состояния кодовой базы.*
