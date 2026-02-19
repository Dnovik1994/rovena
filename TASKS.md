## Задача: Миграция Account → TelegramAccount (#11)
**Приоритет:** P2
**Оценка:** 5-8 дней
**Зависимости:** Нет блокирующих зависимостей — TelegramAccount модель, миграции и API (`tg_accounts.py`) уже существуют
**Риски:**
- Рассогласование полей между моделями (phone → phone_e164, telegram_id → tg_user_id, owner_id → owner_user_id) может привести к неявным ошибкам
- Legacy celery-задачи (`tasks.py`) активно используют Account — параллельная работа старого и нового кода во время миграции
- Alembic-миграция данных из `accounts` в `telegram_accounts` требует маппинга статусов (7 → 10 значений enum)
- `analytics.py` и `admin.py` считают статистику по Account — нужно переключить без потери данных на дашборде

### Контекст
Модель `Account` помечена как DEPRECATED (`backend/app/models/account.py`, строка 1). Новая модель `TelegramAccount` поддерживает per-account API ID, encrypted sessions, атомарные lease-механизмы для verify/warming, и E164-формат телефонов. Однако legacy-код в `workers/tasks.py` (6 celery-задач), `api/v1/accounts.py` (7 эндпоинтов), `analytics.py` и `admin.py` всё ещё работает через Account. Пока оба пути сосуществуют — это источник багов и дублирования.

### Acceptance Criteria
- [ ] Все celery-задачи из `workers/tasks.py` (`account_health_check`, `start_warming`, `check_cooldowns`, `legacy_verify_account`) переписаны на TelegramAccount (или удалены, если дублируют `tg_warming_tasks.py`)
- [ ] API-эндпоинты `api/v1/accounts.py` заменены редиректами на `tg_accounts.py` или удалены, если функционал полностью покрыт
- [ ] `analytics.py` и `admin.py` используют только TelegramAccount для подсчёта статистики
- [ ] Схемы `schemas/account.py` удалены или помечены deprecated
- [ ] Модель `Account` и таблица `accounts` удалены (или оставлена только Alembic-миграция для drop table)
- [ ] Импорт Account удалён из `models/__init__.py`
- [ ] Все существующие тесты проходят без Account-зависимостей
- [ ] Написана Alembic-миграция для переноса данных (если production содержит данные в accounts)

### Предлагаемый план
1. Аудит: составить полный список использований Account в проекте (`grep -r "Account" backend/app/`)
2. Мигрировать `workers/tasks.py`: заменить `_run_account_health_check`, `_run_warming_cycle`, `check_cooldowns`, `_run_legacy_verify` на TelegramAccount-эквиваленты (или делегировать в `tg_warming_tasks.py`)
3. Мигрировать `api/v1/accounts.py`: либо удалить эндпоинты (если `tg_accounts.py` полностью покрывает), либо сделать deprecation-редиректы
4. Обновить `analytics.py` (строки 37-55) и `admin.py` (строки 53-70): заменить Account-запросы на TelegramAccount
5. Удалить `schemas/account.py` и связанные импорты
6. Написать Alembic-миграцию для drop table accounts (если данные уже мигрированы) или data migration
7. Удалить `models/account.py`, обновить `models/__init__.py`
8. Прогнать полный набор тестов, исправить поломки

### Что НЕ входит в задачу
- Рефакторинг TelegramAccount модели или добавление новых полей
- Изменение фронтенд-логики (фронтенд уже использует tg_accounts API)
- Миграция production-данных (отдельная задача DevOps)

---

## Задача: Фронтенд-тесты (vitest + React Testing Library) (#13)
**Приоритет:** P2
**Оценка:** 5-7 дней
**Зависимости:** Нет блокирующих зависимостей
**Риски:**
- Telegram WebApp SDK (window.Telegram.WebApp) требует мокирования — нестандартная среда
- `apiFetch` в `shared/api/client.ts` использует кастомный fetch-wrapper с token refresh и AbortController — сложно мокать
- Zustand store (`stores/auth.tsx`) содержит side-effects (localStorage) — нужен setup/teardown
- 15 страниц + 9 компонентов — объём работы может быть недооценён

### Контекст
Фронтенд (`frontend/`) на React 18 + TypeScript + Vite не имеет ни одного теста. Нет ни vitest, ни jest, ни @testing-library в devDependencies. Для CI/CD и уверенности при рефакторинге необходим базовый тестовый фреймворк с покрытием критичных сценариев: авторизация, API-клиент, ключевые страницы.

### Acceptance Criteria
- [ ] Установлены и настроены: `vitest`, `@testing-library/react`, `@testing-library/user-event`, `jsdom`, `msw`
- [ ] Создан `vitest.config.ts` с правильной конфигурацией (jsdom environment, path aliases из vite.config.ts)
- [ ] Создан `src/test/setup.ts` с глобальными моками (Telegram WebApp, localStorage, matchMedia)
- [ ] Создан хелпер `renderWithProviders()` (React Query + Zustand + Router обёртка)
- [ ] Тесты на Auth-логику: `stores/auth.tsx` — login, logout, token refresh, onboarding state
- [ ] Тесты на API-клиент: `shared/api/client.ts` — success, 401 retry, 429 rate limit, timeout, 5xx
- [ ] Тесты на минимум 3 страницы: Dashboard (рендер, загрузка данных), Login (авторизация), Accounts (CRUD-флоу)
- [ ] Тесты на ErrorBoundary и ErrorState компоненты
- [ ] Скрипт `test` добавлен в `package.json`
- [ ] Все тесты проходят в CI (exit code 0)

### Предлагаемый план
1. Установить зависимости: `npm install -D vitest @testing-library/react @testing-library/user-event @testing-library/dom jsdom msw @vitest/ui`
2. Создать `vitest.config.ts`: extend vite.config.ts, environment: jsdom, setup files
3. Создать `src/test/setup.ts`: mock Telegram WebApp (`window.Telegram = { WebApp: {...} }`), mock localStorage, mock matchMedia
4. Создать `src/test/utils.tsx`: `renderWithProviders()` — оборачивает в QueryClientProvider + AuthProvider + MemoryRouter
5. Написать MSW-хендлеры для основных API-эндпоинтов (`/api/v1/auth/*`, `/api/v1/projects`, etc.)
6. Написать unit-тесты на `stores/auth.tsx` (6-8 кейсов)
7. Написать unit-тесты на `shared/api/client.ts` (5-7 кейсов)
8. Написать component-тесты на Dashboard, Login, Accounts (по 3-5 кейсов)
9. Написать тесты на ErrorBoundary (2-3 кейса)
10. Добавить `"test": "vitest run"` и `"test:watch": "vitest"` в `package.json`
11. Проверить CI-прогон

### Что НЕ входит в задачу
- E2E тесты (Playwright, Cypress)
- Visual regression тесты
- 100% покрытие — цель ≥40% на критичные пути
- Рефакторинг компонентов под тестируемость

---

## Задача: Интеграционные тесты campaign dispatch (#16)
**Приоритет:** P2
**Оценка:** 4-6 дней
**Зависимости:**
- Нужен рабочий mock для pyrogram `Client` (уже частично реализован в `test_invites.py`)
- Нужна тестовая БД с fixtures для InviteCampaign, InviteTask, TelegramAccount, TgUser
**Риски:**
- Celery-задачи используют `asyncio.run()` внутри sync task — в тестах нужен корректный event loop management
- `SELECT FOR UPDATE SKIP LOCKED` (lease механизм) не поддерживается в SQLite — нужен conditional skip или Postgres test container
- Мокирование pyrogram Client с различными exception-типами (FloodWait, PeerFlood, UserPrivacyRestricted) — хрупкие тесты
- Таймеры и sleep-интервалы в dispatch-логике (40-120с) нужно мокать через `unittest.mock.patch`

### Контекст
Новая система InviteCampaign dispatch (`tg_invite_tasks.py`) полностью не покрыта тестами. Существующие тесты (`test_dispatch_errors.py`, `test_invites.py`) покрывают только legacy Campaign dispatch и содержат всего 4 теста на 2 ошибочных сценария + 1 успешный + 1 FloodWait. Новая система имеет 4-фазный dispatch с lease-механизмом, per-account rate limiting, auto-reschedule, и поддержкой множественных error-типов — всё это требует тестирования.

### Acceptance Criteria
- [ ] End-to-end тест: InviteCampaign draft → active → dispatch → все tasks → completed
- [ ] Тест lease-механизма: параллельный dispatch отклоняется, lease освобождается в finally
- [ ] Тест lifecycle InviteTask: pending → in_progress → success/failed/skipped
- [ ] Тест per-account rate limit: account с X invites/hour не получает больше задач
- [ ] Тесты ошибок (по одному на каждый тип):
  - FloodWait → account cooldown, task reverted to pending
  - PeerFlood → task failed, campaign continues
  - UserPrivacyRestricted → task failed, campaign continues
  - UserAlreadyParticipant → task skipped
  - Network timeout → task failed with error message
- [ ] Тест reschedule: если остались pending tasks после цикла — dispatch перепланируется
- [ ] Тест campaign pause: dispatch останавливается если campaign.status != active
- [ ] Тест: пустой список tasks → campaign сразу completed
- [ ] Тест atomic counters: invites_completed и invites_failed корректно инкрементируются
- [ ] Все тесты проходят на SQLite (с conditional skip для SELECT FOR UPDATE)

### Предлагаемый план
1. Создать `backend/tests/test_invite_campaign_dispatch.py`
2. Создать fixtures: helper-функции для создания InviteCampaign, InviteTask, TelegramAccount, TgUser в тестовой БД
3. Создать mock pyrogram Client с конфигурируемыми ответами (success, FloodWait(N), PeerFlood, etc.)
4. Patch `asyncio.sleep` и `random.uniform` для ускорения тестов
5. Написать happy-path тест: полный dispatch цикл от start до completed (3-5 tasks, 1-2 accounts)
6. Написать тест lease: два вызова dispatch для одной campaign — второй возвращает early
7. Написать параметризованные тесты ошибок (`@pytest.mark.parametrize` по error type)
8. Написать тест rate limiting: account с 2 invites/hour, 5 pending tasks → только 2 обработаны
9. Написать тест reschedule: mock `self.apply_async` и проверить countdown=60
10. Написать edge-case тесты: пустые tasks, отсутствующий TgUser, campaign paused mid-dispatch
11. Добавить conditional skip для SQLite-несовместимых тестов (lease с SELECT FOR UPDATE)

### Что НЕ входит в задачу
- Тесты legacy Campaign dispatch (уже частично покрыты)
- WebSocket broadcast тесты (отдельная задача)
- Load/stress тесты
- Тесты API-эндпоинтов invite_campaigns.py (отдельная задача)
- Production Postgres test container setup
