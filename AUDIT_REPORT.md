# Аудит: крупные файлы + диагностика 5 находок

> Дата: 2026-02-19
> Только отчёт — без исправлений.

---

## Часть 1 — Анализ крупных файлов проекта

### 1.1 Backend `.py` файлы (топ-15 по строкам)

| # | Файл | Строк |
|---|------|-------|
| 1 | `workers/tg_auth_tasks.py` | 1641 |
| 2 | `api/v1/tg_accounts.py` | 935 |
| 3 | `workers/tasks.py` | 676 |
| 4 | `workers/tg_warming_tasks.py` | 619 |
| 5 | `main.py` | 587 |
| 6 | `workers/tg_sync_tasks.py` | 513 |
| 7 | `api/v1/admin.py` | 482 |
| 8 | `workers/tg_invite_tasks.py` | 481 |
| 9 | `api/v1/invite_campaigns.py` | 452 |
| 10 | `api/v1/auth.py` | 271 |
| 11 | `core/settings.py` | 264 |
| 12 | `workers/tg_campaign_tasks.py` | 262 |
| 13 | `api/v1/campaigns.py` | 241 |
| 14 | `clients/telegram_client.py` | 202 |
| 15 | `models/telegram_account.py` | 199 |

### 1.2 Frontend `.ts/.tsx` файлы (топ-10)

| # | Файл | Строк |
|---|------|-------|
| 1 | `pages/Admin.tsx` | 995 |
| 2 | `pages/Accounts.tsx` | 710 |
| 3 | `pages/InviteCampaigns.tsx` | 675 |
| 4 | `services/resources.ts` | 416 |
| 5 | `pages/Campaigns.tsx` | 342 |
| 6 | `services/__tests__/websocket.test.ts` | 331 |
| 7 | `pages/AccountChats.tsx` | 312 |
| 8 | `pages/Dashboard.tsx` | 255 |
| 9 | `services/websocket.ts` | 240 |

### 1.3 Workers (отдельно)

| Файл | Строк |
|------|-------|
| `tg_auth_tasks.py` | 1641 |
| `tasks.py` | 676 |
| `tg_warming_tasks.py` | 619 |
| `tg_sync_tasks.py` | 513 |
| `tg_invite_tasks.py` | 481 |
| `tg_campaign_tasks.py` | 262 |
| `__init__.py` | 118 |
| `tg_timeout_helpers.py` | 50 |
| **Итого workers/** | **4360** |

---

### 1.4 Таблица файлов > 300 строк — Backend

| Файл | Строк | Функций/классов | Проблема | Рекомендация по разбиению |
|------|-------|----------------|----------|--------------------------|
| `workers/tg_auth_tasks.py` | 1641 | 27 / 0 | God-file: 5 Celery задач + 22 хелпера + deprecated-код (536 строк). `_run_unified_auth` — 399 строк в одной функции. | Разбить на 4-5 модулей (см. детальный разбор ниже) |
| `api/v1/tg_accounts.py` | 935 | 22 / 0 | 22 эндпоинта в одном роутере: auth flow + CRUD + операции + чаты/участники. | Разбить на 3 роутера: `tg_accounts_crud.py`, `tg_accounts_auth.py`, `tg_accounts_ops.py` |
| `workers/tasks.py` | 676 | 19 / 0 | God-file: dispatch, health-check, warming, cooldown, proxy validation — 5+ несвязанных доменов. | Разбить по домену: `campaign_dispatch_tasks.py`, `health_check_tasks.py`, `proxy_tasks.py`, `task_helpers.py` |
| `workers/tg_warming_tasks.py` | 619 | 22 / 0 | Смешаны уровни абстракции: 8 warming-действий + оркестрация + beat-задачи. | Выделить `warming_actions.py` (действия), оставить оркестрацию в файле, beat → `tg_warming_beat.py` |
| `main.py` | 587 | 30 / 3 | Бизнес-логика в точке входа: Stripe webhook, WebSocket, метрики, bootstrap admin. | WebSocket → `api/v1/websocket.py`, Stripe → `api/v1/webhooks.py`, exception handlers → `core/exception_handlers.py`, middleware → `core/middleware.py` |
| `workers/tg_sync_tasks.py` | 513 | 9 / 0 | Upsert-хелперы переиспользуемы, но живут в task-файле. Умеренная проблема. | Извлечь upsert-хелперы в `services/tg_user_sync.py`. Остаток: ~300 строк оркестрации |
| `api/v1/admin.py` | 482 | 15 / 2 | 5 несвязанных доменов: users, tariffs, billing/Stripe, proxies, accounts. | Минимум отделить Stripe-биллинг. Идеально: по файлу на домен |
| `workers/tg_invite_tasks.py` | 481 | 6 / 0 | `_run_invite_campaign_dispatch_inner` — ~300 строк с вложенностью 4+ уровней. | Разбить на `_pick_accounts()`, `_claim_tasks()`, `_process_account_batch()`, `_finalize_campaign()` |
| `api/v1/invite_campaigns.py` | 452 | 8 / 0 | `create_invite_campaign` — ~140 строк с тяжёлой query-логикой. | Извлечь member-selection в `services/invite_member_selection.py` |

### 1.5 Таблица файлов > 300 строк — Frontend

| Файл | Строк | Компонентов/функций | Проблема | Рекомендация по разбиению |
|------|-------|-------|----------|--------------------------|
| `pages/Admin.tsx` | 995 | 1 компонент, 11 мутаций, 6 запросов, 2 схемы, ~26 лог. единиц | God-компонент: 6 независимых табов с полной логикой каждый. | Каждый таб → отдельный компонент: `AdminStats`, `AdminUsers`, `AdminTariffs` и т.д. Схемы → `admin.schemas.ts` |
| `pages/Accounts.tsx` | 710 | 1 компонент, 3 схемы, 9 обработчиков, ~22 лог. единицы | Многошаговый auth flow (polling + WS + 3 формы) — всё в одном компоненте. | Извлечь `useAuthFlow` хук, `AccountCard` компонент, схемы → `accounts.schemas.ts` |
| `pages/InviteCampaigns.tsx` | 675 | 3 компонента, 10 обработчиков, ~16 лог. единиц | Двойной polling (list + detail) через raw `setInterval`/refs. Модалка создания инлайн. | Извлечь `CreateCampaignModal`, `CampaignCard`, polling → `useCampaignPolling` хук |
| `services/resources.ts` | 416 | 34 экспортированные функции | Barrel-файл: 34 API-функций для 8+ доменов. Любое изменение — merge conflict. | Разбить по домену: `services/projects.ts`, `services/tgAccounts.ts`, `services/admin.ts` и т.д. |
| `pages/Campaigns.tsx` | 342 | 1 компонент, 1 схема, 4 обработчика, ~10 лог. единиц | Умеренная. WebSocket + Telegram WebApp MainButton + формы в одном компоненте. | Извлечь `CampaignForm`, `CampaignCard`, `useTelegramMainButton` хук. Низкий приоритет |
| `pages/AccountChats.tsx` | 312 | 3 функции, 4 обработчика, 3 ref-карты для polling | `handleParse` — 85 строк с тройным ref-management. Дублирует `extractError`. | Извлечь `useParsePolling` хук, `ChatCard` компонент. Удалить дубль `extractError` |

---

### 1.6 Детальный разбор `tg_auth_tasks.py` (1641 строк)

#### Полный список функций

| # | Функция | Строки | Длина | Декоратор/тип |
|---|---------|--------|-------|---------------|
| 1 | `_mask_phone` | 64-70 | 7 | private helper |
| 2 | `_sanitize_error` | 76-78 | 3 | private helper |
| 3 | `_broadcast_account_update` | 81-87 | 7 | private helper |
| 4 | `_broadcast_flow_update` | 90-97 | 8 | private helper |
| 5 | `_handle_floodwait` | 100-107 | 8 | private helper |
| 6 | `_mark_proxy_unhealthy` | 110-117 | 8 | private helper |
| 7 | `_is_network_error` | 120-123 | 4 | private helper |
| 8 | `_log_client_fingerprint` | 126-143 | 18 | private helper |
| 9 | `_get_dc_id` | 146-157 | 12 | async helper |
| 10 | `_set_dc_id` | 160-164 | 5 | async helper |
| 11 | `_is_dc_migrate_error` | 167-168 | 2 | private helper |
| 12 | `_extract_migrate_dc` | 171-176 | 6 | private helper |
| 13 | `_pre_auth_session_name` | 187-189 | 3 | private helper |
| 14 | `_pre_auth_session_path` | 192-194 | 3 | private helper |
| 15 | `_ensure_pre_auth_dir` | 197-232 | 36 | private helper |
| 16 | `_cleanup_pre_auth_session` | 235-244 | 10 | private helper |
| 17 | `_read_session_auth_key` | 247-284 | 38 | private helper |
| 18 | `_run_send_code` | 291-475 | **185** | async **(deprecated)** |
| 19 | `send_code_task` | 478-504 | 27 | `@celery_app.task` **(deprecated)** |
| 20 | `_run_confirm_code` | 511-794 | **284** | async **(deprecated)** |
| 21 | `confirm_code_task` | 797-822 | 26 | `@celery_app.task` **(deprecated)** |
| 22 | `_run_unified_auth` | 827-1225 | **399** | async (основной flow) |
| 23 | `unified_auth_task` | 1228-1262 | 35 | `@celery_app.task` (основной) |
| 24 | `_run_confirm_password` | 1267-1432 | **166** | async |
| 25 | `confirm_password_task` | 1435-1459 | 25 | `@celery_app.task` |
| 26 | `_run_verify_account` | 1464-1615 | **152** | async |
| 27 | `verify_account_task` | 1618-1641 | 24 | `@celery_app.task` |

#### Логические группы

| Группа | Строки | Размер | Функции |
|--------|--------|--------|---------|
| **A — Утилиты** | 64-176 | ~113 | `_mask_phone`, `_sanitize_error`, `_broadcast_*`, `_handle_floodwait`, `_mark_proxy_unhealthy`, `_is_network_error`, `_log_client_fingerprint`, `_get_dc_id`, `_set_dc_id`, `_is_dc_migrate_error`, `_extract_migrate_dc` |
| **B — Pre-auth сессии** | 179-284 | ~106 | `_pre_auth_session_name`, `_pre_auth_session_path`, `_ensure_pre_auth_dir`, `_cleanup_pre_auth_session`, `_read_session_auth_key` |
| **C — Deprecated two-step** | 287-822 | **~536** | `_run_send_code`, `send_code_task`, `_run_confirm_code`, `confirm_code_task` |
| **D — Unified auth** | 825-1262 | **~438** | `_run_unified_auth`, `unified_auth_task` |
| **E — 2FA пароль** | 1265-1459 | ~195 | `_run_confirm_password`, `confirm_password_task` |
| **F — Верификация** | 1462-1641 | ~180 | `_run_verify_account`, `verify_account_task` |

#### Предложение: разбиение на 5 модулей

| Новый модуль | Строк | Что содержит | Статус |
|-------------|-------|--------------|--------|
| `tg_auth_helpers.py` | ~219 | Группы A + B: все утилиты и pre-auth session management | Shared |
| `tg_auth_unified_task.py` | ~438 | Группа D: `_run_unified_auth` + `unified_auth_task` | Active (production) |
| `tg_auth_password_task.py` | ~195 | Группа E: `_run_confirm_password` + `confirm_password_task` | Active (2FA) |
| `tg_auth_verify_task.py` | ~180 | Группа F: `_run_verify_account` + `verify_account_task` | Active (health check) |
| `tg_auth_legacy_tasks.py` | ~536 | Группа C: deprecated send_code + confirm_code | Deprecated → удалить |

> **Примечание:** `_run_unified_auth` (399 строк) — кандидат на дальнейшую внутреннюю декомпозицию: выделить polling-loop и sign-in-with-retry в отдельные sub-функции.

---

## Часть 2 — Диагностика 5 находок

---

### Находка A — PeerFlood НЕ ставит account в cooldown

**Файл:** `backend/app/workers/tg_invite_tasks.py`

#### Обработка FloodWait (строки 338-357):

```python
except FloodWait as exc:
    sentry_sdk.capture_exception(exc)
    logger.warning(
        "invite_dispatch: FloodWait %ds account_id=%d campaign=%d",
        exc.value, acct_id, campaign_id,
    )
    # Revert task to pending
    with SessionLocal() as db:
        task = db.get(InviteTask, task_id)
        if task:
            task.status = InviteTaskStatus.pending
            task.account_id = None
            db.commit()
        # ✅ Set account cooldown
        account = db.get(TelegramAccount, acct_id)
        if account:
            account.status = TelegramAccountStatus.cooldown
            account.cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=exc.value)
            db.commit()
    account_broke = True
```

#### Обработка PeerFlood (строки 359-370):

```python
except PeerFlood as exc:
    sentry_sdk.capture_exception(exc)
    logger.warning("invite_dispatch: PeerFlood account_id=%d", acct_id)
    with SessionLocal() as db:
        task = db.get(InviteTask, task_id)
        if task:
            task.status = InviteTaskStatus.failed
            task.error_message = "PeerFlood"
            task.completed_at = datetime.now(timezone.utc)
            db.commit()
        _atomic_increment(db, campaign_id, "invites_failed")
    account_broke = True
    # ❌ НЕТ: account.status = cooldown
    # ❌ НЕТ: account.cooldown_until = ...
```

#### Разница

| | FloodWait | PeerFlood |
|-|-----------|-----------|
| Task status | `pending` (retry) | `failed` (permanent) |
| Account → cooldown | **Да** (`cooldown_until = now + exc.value`) | **Нет** |
| `account_broke` | `True` (stop loop) | `True` (stop loop) |
| Задачи текущей пачки | Revert to pending | Remain as failed |

#### Сценарий проблемы

`account_broke = True` останавливает текущий цикл для этого account в **текущем** dispatch-раунде. Но через 60 секунд произойдёт reschedule (`apply_async(countdown=60)`). В новом раунде этот account по-прежнему имеет `status = active` → он снова будет выбран для инвайтов → снова получит PeerFlood → и так в цикле.

**Результат:** Account молотит Telegram API каждые ~60 секунд, получая PeerFlood. При повторных PeerFlood Telegram может выдать **временный бан**, а при продолжении — **перманентный бан** аккаунта.

**Критичность:** 🔴 **Высокая** — прямой путь к бану аккаунтов.

**Рекомендация:** При PeerFlood ставить account в cooldown на 1-4 часа (без точного `exc.value`, потому что PeerFlood не содержит таймер).

---

### Находка B — Нет reschedule при отсутствии active accounts

**Файл:** `backend/app/workers/tg_invite_tasks.py`, строки 142-144

#### Точный код:

```python
if not account_ids:
    logger.warning("invite_dispatch: no active accounts for owner_id=%d campaign=%d", owner_id, campaign_id)
    return  # ← ранний выход, нет reschedule
```

#### Что происходит дальше

После `return` — управление попадает в блок `finally` в `_run_invite_campaign_dispatch` (строка 101-108), который только освобождает lease. **Reschedule не вызывается.**

Reschedule происходит только в Phase 4 (строки 436-446), до которой код не доходит при раннем return.

#### Сценарий проблемы

1. Все аккаунты владельца в `cooldown` (например, после FloodWait)
2. Dispatch запускается → `account_ids = []` → `return`
3. Campaign остаётся в статусе `active`, но **никто больше не вызывает** `invite_campaign_dispatch`
4. В `beat_schedule` **нет** периодической задачи для invite campaigns (проверено — есть только `check_tg_cooldowns` и `resume_tg_warming`)
5. Campaign **зависает навсегда** — пока пользователь вручную не нажмёт "Resume"

#### Есть ли внешний scheduler?

**Нет.** `beat_schedule` содержит только:
- `check-tg-cooldowns-every-2-min` → `tg_warming_tasks.check_tg_cooldowns`
- `resume-tg-warming-every-5-min` → `tg_warming_tasks.resume_tg_warming`

Invite campaigns не имеют периодического "подхватчика".

**Критичность:** 🔴 **Высокая** — campaign зависает без возможности автоматического восстановления.

**Рекомендация:** При пустых `account_ids` делать `apply_async(countdown=120)` для retry. Либо добавить beat-задачу `resume_stalled_invite_campaigns`, которая раз в 5 минут проверяет active campaigns без `dispatch_task_id`.

---

### Находка C — Бесконечный WebSocket reconnect

**Файл:** `frontend/src/services/websocket.ts`

#### Код reconnect loop (строки 146-151 + 171-187):

```typescript
const scheduleReconnect = () => {
    if (disposed) return;
    const delay = computeBackoff(attempt);
    attempt += 1;
    reconnectTimer = setTimeout(connect, delay);
};

// ...

ws.onclose = (ev: CloseEvent) => {
    clearTimers();

    if (disposed) {
        setState("disconnected");
        return;
    }

    if (ev.code === AUTH_FAILURE_CODE) {   // 1008
        setState("auth_failed");
        console.warn("[ws] Auth failed (1008) — will not retry");
        return;     // ← единственный случай остановки
    }

    setState("disconnected");
    scheduleReconnect();  // ← retry ВСЕГДА при любом другом close
};
```

#### Backoff параметры (строки 46-58):

```typescript
const BASE_DELAY_MS = 250;
const MAX_DELAY_MS = 30_000;    // cap = 30 секунд

export const computeBackoff = (attempt: number): number => {
    const exp = Math.min(BASE_DELAY_MS * Math.pow(2, attempt), MAX_DELAY_MS);
    const jitter = exp * JITTER_FACTOR * (Math.random() * 2 - 1);
    return Math.max(0, Math.round(exp + jitter));
};
```

#### Сценарий проблемы

Если сервер **навсегда** недоступен (deployment упал, DNS-проблема, firewall):

- Backoff: 250ms → 500ms → 1s → 2s → 4s → 8s → 16s → **30s** (cap)
- С attempt 7+ delay = ~30s (±jitter)
- **~2880 попыток/сутки** при cap 30s
- Нет `maxAttempts` — reconnect не остановится **никогда** (пока не вызван `dispose()`)
- Каждая попытка — DNS lookup + TCP handshake attempt → нагрузка на DNS и сеть

#### Смягчающие факторы

- Auth failure (1008) корректно останавливает retry
- Singleton guard предотвращает параллельные соединения
- `dispose()` при unmount компонента корректно останавливает

**Критичность:** 🟡 **Средняя** — не критично при нормальной работе, но при длительном offline:
- Батарея мобильных устройств
- Лишняя нагрузка на DNS/балансер
- Потенциальный flood если много клиентов одновременно

**Рекомендация:** Добавить `maxAttempts` (например, 50) или суммарный TTL (например, 10 минут). После лимита — `setState("disconnected")` и показать юзеру кнопку "Reconnect".

---

### Находка D — Нет дедупликации refresh в HTTP-клиенте

**Файл:** `frontend/src/shared/api/client.ts`, строки 98-103

#### Точный код:

```typescript
if (response.status === 401 && retryOnUnauthorized && !path.includes("/auth/refresh")) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
        return apiFetch<T>(path, options, refreshed, false, timeoutMs);
    }
}
```

#### Функция `refreshAccessToken` (строки 135-172):

```typescript
export const refreshAccessToken = async (): Promise<string | null> => {
    const { refreshToken } = getStoredTokens();
    if (!refreshToken) {
        return null;
    }

    // ...
    let response: Response;
    try {
        response = await fetch(`${API_BASE_URL}/auth/refresh`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ refresh_token: refreshToken }),
            signal: controller.signal,
        });
    } catch {
        clearTimeout(timer);
        clearStoredTokens();
        return null;
    }
    // ...
};
```

#### Сценарий проблемы

1. 5 параллельных `apiFetch` запросов отправлены с валидным access token
2. Access token истекает → все 5 получают `401`
3. Каждый из 5 **независимо** вызывает `refreshAccessToken()`
4. Запрос #1 отправляет refresh → получает новый access + **новый refresh token**
5. Запросы #2-#5 отправляют refresh с **уже невалидным** старым refresh token

**Результат зависит от бэкенда:**
- Если backend практикует **refresh token rotation** (одноразовый refresh) → запросы #2-#5 получат ошибку → `clearStoredTokens()` → **пользователя разлогинивает**
- Если backend допускает повторное использование refresh token → проблема мягче, но всё равно 5 лишних HTTP-запросов

**Отсутствует:** mutex/promise deduplication паттерн:
```typescript
// Чего нет:
let refreshPromise: Promise<string | null> | null = null;
```

**Критичность:** 🔴 **Высокая** (если refresh token одноразовый) / 🟡 **Средняя** (если нет)

**Рекомендация:** Ввести shared promise: если refresh уже в полёте — ждать его результата, а не запускать новый. Классический паттерн:
```typescript
let inflightRefresh: Promise<string | null> | null = null;

export const refreshAccessToken = async () => {
    if (inflightRefresh) return inflightRefresh;
    inflightRefresh = doRefresh().finally(() => { inflightRefresh = null; });
    return inflightRefresh;
};
```

---

### Находка E — `extractError` не валидирует тип `message`

**Файл:** `frontend/src/utils/extractError.ts` (полный файл, 6 строк)

#### Точный код:

```typescript
export function extractError(err: unknown): string {
    if (err && typeof err === "object" && "message" in err) {
        return (err as { message: string }).message;
    }
    return "Unexpected error";
}
```

#### Проблема

Проверка `"message" in err` гарантирует только **наличие** свойства `message`, но не его **тип**. Cast `as { message: string }` — ложный: TypeScript не проверяет runtime-тип.

#### Сценарий

```typescript
// Если API вернёт:
const err = { message: { nested: "object" } };

extractError(err);
// → возвращает { nested: "object" }  (объект, не строку)

// Если API вернёт:
const err2 = { message: 42 };

extractError(err2);
// → возвращает 42  (число, не строку)

// Если API вернёт:
const err3 = { message: null };

extractError(err3);
// → возвращает null
```

**Что произойдёт в UI:** React вызовет `{errorMessage}` в JSX. Для `null`/`number` — React отрендерит как текст (безвредно). Для **объекта** — `Objects are not valid as a React child` → **белый экран** (uncaught error в рендере).

**Критичность:** 🟢 **Низкая** — маловероятно что API вернёт `message` как объект, но при экзотических ошибках возможен краш UI.

**Рекомендация:** Добавить проверку типа:
```typescript
export function extractError(err: unknown): string {
    if (err && typeof err === "object" && "message" in err) {
        const msg = (err as Record<string, unknown>).message;
        if (typeof msg === "string") return msg;
        return String(msg);
    }
    return "Unexpected error";
}
```

---

## Итоговая сводка

| Находка | Описание | Критичность | Effort | Рекомендация |
|---------|----------|------------|--------|-------------|
| **A** | PeerFlood не ставит account в cooldown | 🔴 Высокая | 15 мин | Добавить `account.status = cooldown`, `cooldown_until = now + 2h` при PeerFlood |
| **B** | Нет reschedule при пустых active accounts | 🔴 Высокая | 30 мин | Добавить `apply_async(countdown=120)` при раннем return ИЛИ beat-задачу `resume_stalled_invite_campaigns` |
| **C** | Бесконечный WebSocket reconnect | 🟡 Средняя | 20 мин | Добавить `maxAttempts` или TTL, после лимита — показать кнопку reconnect |
| **D** | Race condition при параллельном refresh | 🔴 Высокая* | 15 мин | Ввести shared promise (inflight deduplication). *Критичность зависит от rotate-политики refresh token |
| **E** | `extractError` не валидирует тип `message` | 🟢 Низкая | 5 мин | Добавить `typeof msg === "string"` проверку |

> \* Находка D — 🔴 если backend ротирует refresh tokens (одноразовые), 🟡 если допускает повторное использование.
