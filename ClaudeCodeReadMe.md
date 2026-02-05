# ClaudeCodeReadMe - Полный анализ проекта Rovena (FreeCRM Inviter)

> Автоматический анализ проекта, выполненный Claude Code. Дата: 2026-02-05

---

## 1. Общее описание проекта

**Rovena (FreeCRM Inviter)** - это полнофункциональная платформа для автоматизации массовых приглашений пользователей в Telegram-группы и каналы. Проект реализован как **Telegram Mini App** (WebApp) с полным стеком: бэкенд на FastAPI, фронтенд на React, инфраструктура на Docker с мониторингом.

### Основная бизнес-логика

1. **Управление Telegram-аккаунтами** - подключение, верификация (2FA), прогрев (warming), генерация конфигурации устройств для обхода детекции
2. **Система кампаний** - создание массовых инвайт-кампаний из source-групп в target-группы с контролем лимитов (в час/день)
3. **Управление контактами** - формирование списков контактов, тегирование, блокировка
4. **Прокси-сервер** - поддержка HTTP, SOCKS5, residential-прокси для ротации аккаунтов
5. **Тарифная система** - подписки через Stripe с лимитами по количеству аккаунтов и инвайтов
6. **Онбординг** - пошаговый процесс настройки для новых пользователей

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
| Axios | 1.7.7 | HTTP-клиент |

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
| GitHub Actions | CI/CD |

---

## 3. Архитектура проекта

```
rovena/
├── backend/                    # FastAPI backend (Python 3.12)
│   ├── app/
│   │   ├── api/v1/             # REST API endpoints (9 модулей)
│   │   ├── models/             # SQLAlchemy модели (9 таблиц)
│   │   ├── schemas/            # Pydantic-схемы запросов/ответов
│   │   ├── services/           # Бизнес-логика (proxy_sync, websocket)
│   │   ├── clients/            # Внешние интеграции (Telegram)
│   │   ├── core/               # Ядро (settings, auth, cache, RBAC)
│   │   ├── workers/            # Celery-задачи
│   │   └── utils/              # Утилиты
│   ├── alembic/                # 17 миграций БД
│   ├── tests/                  # 25+ тестов
│   └── Dockerfile
├── frontend/                   # React SPA (TypeScript)
│   ├── src/
│   │   ├── pages/              # 11 страниц
│   │   ├── components/         # Переиспользуемые компоненты
│   │   ├── services/           # API + WebSocket клиенты
│   │   ├── stores/             # Zustand-сторы
│   │   └── types/              # TypeScript-интерфейсы
│   ├── Dockerfile / Dockerfile.dev
│   └── nginx.conf
├── proxy/                      # 3proxy контейнер
├── docs/                       # Документация (8 файлов)
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

## 4. Текущий этап проекта

### Что реализовано (80-85% MVP)

- Полная аутентификация через Telegram initData + JWT с refresh-токенами
- CRUD для всех основных сущностей (projects, accounts, campaigns, contacts, sources, targets)
- Система ролей (user/admin/superadmin) с RBAC
- Верификация Telegram-аккаунтов (2FA, phone code)
- Прогрев аккаунтов (warming actions)
- Генерация конфигурации устройств (device fingerprint)
- Celery-задачи для рассылки кампаний
- WebSocket для real-time статуса
- Stripe-интеграция для подписок
- Прокси-менеджмент с автоматической синхронизацией конфигурации 3proxy
- Docker-инфраструктура (dev + prod)
- Мониторинг (Prometheus + Grafana)
- CI/CD через GitHub Actions
- Бэкапы БД через cron
- Нагрузочное тестирование (Locust)
- 25+ unit-тестов
- Документация (deploy checklist, smoke tests, security)

### Что НЕ завершено

1. **Dashboard** - страница полностью пустая, содержит только placeholder-текст
2. **Proxy Validation** - эндпоинт `/proxies/validate` возвращает hardcoded `{"valid": true}` без реальной проверки
3. **Account Health Check** - Celery-задача `account_health_check` - stub, не выполняет проверку
4. **Deploy Pipeline** - GitHub Actions deploy job содержит placeholder, не настроен
5. **Subscription Page** - интеграция с Stripe начата, но UI не доработан
6. **Онбординг** - процесс определён, но не полностью интегрирован

---

## 5. Найденные ошибки и проблемы

### 5.1 Критические проблемы безопасности

#### 5.1.1 Shell Injection в proxy_sync
**Файл:** `backend/app/services/proxy_sync.py:51`
```python
subprocess.check_call(settings.proxy_reload_cmd, shell=True)
```
Использование `shell=True` с командой из конфигурации создаёт вектор для shell-инъекции. Если `proxy_reload_cmd` будет модифицирован (через .env или уязвимость), злоумышленник получит выполнение произвольных команд.

**Рекомендация:** Использовать `shell=False` и передавать команду как список, или захардкодить конкретную команду reload.

#### 5.1.2 Небезопасное преобразование типов в JWT
**Файл:** `backend/app/main.py:329`
```python
user_id = int(payload.get("sub", 0))
```
`ValueError` при невалидном payload, вместо корректной обработки токена. Аналогичная проблема в Stripe webhook (`main.py:308-315`) с `int(user_id)` и `int(tariff_id)` без try-catch.

#### 5.1.3 Опасный setattr() без фильтрации полей
**Файлы:** `backend/app/api/v1/accounts.py:86`, `admin.py:281`, `proxies.py:56`
```python
for field, value in payload.model_dump(exclude_unset=True).items():
    setattr(account, field, value)
```
Позволяет потенциально перезаписать `id`, `owner_id`, `user_id` и другие защищённые поля. Необходима явная фильтрация допустимых полей.

#### 5.1.4 WebSocket токен в URL
**Файлы:** `backend/app/main.py:322`, `frontend/src/services/websocket.ts:26`
```python
token = websocket.query_params.get("token")
```
Токен в URL сохраняется в логах сервера, истории браузера, прокси-логах. Необходимо передавать через WebSocket subprotocol или первое сообщение.

#### 5.1.5 Захардкоженные credentials
**Файлы:**
- `backend/app/utils/db_readiness.py:31,38` - пароль `"rovena"` по умолчанию
- `backend/app/core/settings.py:23` - JWT secret `"change-me"`
- `docker-compose.yml:18-19` - MYSQL_PASSWORD `rovena`
- `docker-entrypoint-initdb.d/init-rovena.sql:2` - пользователь `rovena`@`%` с паролем `rovena`

#### 5.1.6 Docker Socket в production
**Файл:** `docker-compose.prod.yml:34`
```yaml
- /var/run/docker.sock:/var/run/docker.sock:ro
```
Даже read-only доступ к Docker socket позволяет просматривать env-переменные всех контейнеров (включая секреты).

---

### 5.2 Логические ошибки

#### 5.2.1 Race condition в dispatch кампаний
**Файл:** `backend/app/workers/tasks.py:86-244`
- Статус кампании может измениться между проверкой и обработкой
- Статус аккаунта может измениться во время цикла рассылки
- Нет блокировок (database locking) для конкурентного доступа

#### 5.2.2 WebSocket Manager - утечка памяти
**Файл:** `backend/app/services/websocket_manager.py:37-42`
```python
def broadcast_sync(self, payload):
    try:
        asyncio.run(self.broadcast(payload))  # Создаёт новый event loop каждый раз
    except RuntimeError:
        loop = asyncio.get_event_loop()
        loop.create_task(self.broadcast(payload))
```
`asyncio.run()` создаёт новый event loop при каждом вызове - крайне неэффективно. Также stale-соединения удаляются неатомарно.

#### 5.2.3 Celery + asyncio.run()
**Файл:** `backend/app/workers/tasks.py:256`
```python
def campaign_dispatch(campaign_id: int) -> None:
    asyncio.run(_run_campaign_dispatch(campaign_id))
```
Использование `asyncio.run()` в Celery-задачах проблематично в production. Celery prefork workers не предназначены для async-кода.

#### 5.2.4 Отсутствие транзакционной изоляции
**Файл:** `backend/app/api/v1/accounts.py:128-133`
Конкурентные запросы могут привести к несогласованному состоянию аккаунтов (status, warming_started_at) без isolation level.

#### 5.2.5 device_config default - мутабельный объект
**Файл:** `backend/app/models/account.py:32`
```python
device_config: Mapped[dict | None] = mapped_column(JSON, default=generate_device_config)
```
Передача функции напрямую как default вместо `default_factory` может привести к общему dict-объекту между инстансами.

---

### 5.3 Проблемы валидации

#### 5.3.1 JSON parsing без обработки ошибок
**Файл:** `backend/app/api/v1/auth.py:36-37`
```python
user_payload = json.loads(user_raw)  # Нет try-catch
telegram_id = int(user_payload["id"])  # KeyError при отсутствии ключа
```

#### 5.3.2 Отсутствие валидации диапазонов в кампаниях
**Файл:** `backend/app/api/v1/campaigns.py:60-63`
- Нет проверки что `max_invites_per_hour` и `max_invites_per_day` > 0
- Нет проверки что `start_at` < `end_at`
- Нет проверки что даты в будущем

#### 5.3.3 Нет валидации Stripe webhook signature
**Файл:** `backend/app/main.py:294`
Если `stripe-signature` header отсутствует, `None` передаётся в `construct_event`, что приведёт к неинформативной ошибке.

---

### 5.4 Проблемы фронтенда

#### 5.4.1 Отсутствие reconnection для WebSocket
**Файл:** `frontend/src/services/websocket.ts:20-48`
При закрытии соединения нет автоматического переподключения. Потеря сети = потеря real-time обновлений без восстановления.

#### 5.4.2 Отсутствие heartbeat/ping-pong
WebSocket может быть молча отключён без уведомления приложения.

#### 5.4.3 Пропущенные зависимости в useEffect
**Файлы:** Все основные страницы (Projects, Sources, Targets, Contacts, Campaigns, Accounts)
```typescript
useEffect(() => {
  fetchData();  // fetchData не в массиве зависимостей
}, [token]);
```
Может приводить к stale closures, пропущенным обновлениям или infinite loops.

#### 5.4.4 Нет таймаутов на fetch-запросы
**Файл:** `frontend/src/services/api.ts:41`
Запросы могут зависнуть навсегда без timeout. Нет retry-логики для сетевых ошибок.

#### 5.4.5 Молчаливое игнорирование ошибок WebSocket
**Файл:** `frontend/src/services/websocket.ts:42-44`
```typescript
catch (error) {
  return;  // Молча игнорирует ошибки парсинга JSON
}
```

#### 5.4.6 Отсутствие Error Boundary
Нет React Error Boundary компонента. Ошибка в любом компоненте крашит всё приложение.

#### 5.4.7 Проблемы доступности (a11y)
- Нет `role="alert"` на Toast-уведомлениях
- Формы без `htmlFor`/`aria-labelledby` на лейблах
- Статусы обозначены только цветом (недоступны для дальтоников)
- Loading-скелетоны без `aria-busy="true"`

---

### 5.5 Проблемы инфраструктуры

#### 5.5.1 Непиннированные версии Docker-образов
**Файлы:** `docker-compose.prod.yml`
- `traefik:latest` (строка 13)
- `prom/prometheus:latest` (строка 231)
- `grafana/grafana:latest` (строка 251)
- `prom/blackbox-exporter:latest` (строка 267)

**Риск:** Неконтролируемые обновления могут сломать деплой.

#### 5.5.2 Нет лимитов ресурсов (CPU/Memory)
Ни один сервис не имеет `deploy.resources.limits`. Один контейнер может потребить все ресурсы хоста.

#### 5.5.3 Нет сетевой изоляции
Все сервисы в одной default-сети. Фронтенд может обращаться к БД напрямую.

#### 5.5.4 Неполный мониторинг
- Prometheus: только 2 scrape-job (backend + blackbox)
- Нет метрик Redis, MySQL, Traefik, Nginx
- Только 2 alerting-правила (HighQueue, ManyBlockedAccounts)
- Нет алертов на CPU, память, диск, доступность сервисов

#### 5.5.5 Имя volume не соответствует БД
**Файл:** `docker-compose.yml:23,229`
Volume назван `postgres-data`, но используется для MySQL.

#### 5.5.6 Неполный CI/CD
- Deploy job в GitHub Actions содержит placeholder
- Нет автоматического деплоя при merge в main
- Нет smoke-тестов после деплоя
- Нет стратегии rollback

#### 5.5.7 Бэкапы без верификации
- `crontab.txt`: нет проверки успешности mysqldump
- Нет проверки целостности бэкапов (checksums)
- Нет документированной процедуры восстановления
- Только 7-дневное хранение

---

## 6. Потенциальные возможности и рекомендации

### 6.1 Немедленные исправления (Critical)

1. **Заменить `shell=True`** в `proxy_sync.py` на `shell=False` с явным списком аргументов
2. **Добавить try-catch** на все `int()` преобразования в auth и webhook обработчиках
3. **Заменить `setattr()`** на явный маппинг допустимых полей во всех endpoint'ах
4. **Перенести WebSocket-токен** из URL query params в subprotocol или первое сообщение
5. **Убрать hardcoded credentials** из кода, использовать только env-переменные без дефолтов
6. **Пиннить Docker-образы** на конкретные версии
7. **Добавить Error Boundary** в React-приложение

### 6.2 Важные улучшения (High Priority)

1. **WebSocket reconnection** - реализовать экспоненциальный backoff при переподключении
2. **Пагинация** - добавить на все list-эндпоинты (сейчас `.all()` загружает всё в память)
3. **Database locking** - добавить `SELECT FOR UPDATE` в критических секциях (campaign dispatch)
4. **Celery async** - заменить `asyncio.run()` на `asgiref.sync_to_async` или sync-реализацию
5. **Сетевая изоляция** - разделить Docker-сети (frontend, backend, db-only)
6. **Resource limits** - добавить CPU/memory limits на все контейнеры
7. **Расширить мониторинг** - добавить MySQL, Redis, Traefik экспортёры и alerting-правила
8. **Fetch timeouts** - добавить AbortController с таймаутом на все API-запросы фронтенда

### 6.3 Средний приоритет

1. **Завершить Dashboard** - добавить графики, статистику кампаний, состояние аккаунтов
2. **Реализовать proxy validation** - реальная проверка прокси вместо hardcoded true
3. **Реализовать account_health_check** - периодическая проверка статуса аккаунтов
4. **Доработать CI/CD** - настроить автоматический деплой, smoke-тесты, rollback
5. **Добавить кэш-инвалидацию** - при изменении данных пользователя/тарифа
6. **Расширить тесты** - покрытие edge-cases, integration-тесты
7. **Доступность (a11y)** - ARIA-атрибуты, корректные лейблы форм, не только цветовые индикаторы
8. **Верификация бэкапов** - checksums, тестовое восстановление, уведомления при сбое

### 6.4 Потенциальные фичи

1. **Аналитика кампаний** - графики конверсии, success rate, blocked rate по времени
2. **Шедулинг кампаний** - запуск по расписанию с учётом часовых поясов
3. **Импорт/экспорт контактов** - CSV/Excel для массового импорта
4. **Шаблоны сообщений** - приветственные сообщения при инвайте
5. **Telegram Bot уведомления** - уведомления о статусе кампаний через бота
6. **Multi-tenant** - изоляция данных между организациями
7. **API Rate Limiting Dashboard** - визуализация использования лимитов
8. **Account Pool Rotation** - автоматическая ротация аккаунтов при блокировке
9. **Smart Cooling** - ML-based определение оптимальных пауз между инвайтами
10. **Webhook-уведомления** - интеграция с внешними системами (Slack, Discord, CRM)

---

## 7. Оценка зрелости проекта

| Аспект | Статус | Оценка |
|---|---|---|
| Backend API | Почти готов | 85% |
| Frontend UI | Базовый функционал | 70% |
| Аутентификация | Реализована | 90% |
| Telegram-интеграция | Работает | 80% |
| Платежи (Stripe) | Базовая интеграция | 50% |
| Мониторинг | Базовый | 40% |
| CI/CD | Частично | 35% |
| Тестирование | Базовое покрытие | 45% |
| Документация | Хорошая | 75% |
| Безопасность | Требует доработки | 55% |
| DevOps/Infra | Настроено | 65% |
| **Общая оценка** | **MVP стадия** | **~65%** |

### Вывод

Проект находится на стадии **позднего MVP**. Основной функционал реализован и архитектурно продуман. Backend имеет грамотную структуру с разделением ответственности. Инфраструктура подготовлена для production (Traefik, мониторинг, бэкапы). Однако перед production-релизом необходимо закрыть критические проблемы безопасности, доработать валидацию, реализовать stub-эндпоинты и обеспечить стабильность WebSocket-соединений.

---

*Этот документ сгенерирован автоматически на основе полного анализа кодовой базы. Рекомендуется использовать как roadmap для дальнейшей разработки.*
