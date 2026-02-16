# Аудит фоновых задач (Background Tasks Stability Audit)

Дата: 2026-02-16

---

## Обнаруженные задачи

### Celery Tasks — `backend/app/workers/tasks.py`
1. `campaign_dispatch` (строка 277)
2. `account_health_check` (строка 289)
3. `start_warming` (строка 445)
4. `perform_warming_action` (строка 456)
5. `check_cooldowns` (строка 462)
6. `sync_3proxy_config` (строка 490)
7. `validate_proxy_task` (строка 496)
8. `legacy_verify_account` (строка 502)

### Celery Tasks — `backend/app/workers/tg_auth_tasks.py`
9. `send_code_task` (строка 375)
10. `confirm_code_task` (строка 630)
11. `confirm_password_task` (строка 782)
12. `verify_account_task` (строка 934)

### Asyncio Tasks — `backend/app/main.py`
13. `_redis_ws_subscriber` (строка 148)
14. `_ping_loop` (строка 536)

---

## 1. `campaign_dispatch` — tasks.py:277

| Критерий | Статус |
|---|---|
| Модель | 🟡 Legacy `Account` (TODO на строке 115) |
| Fallback без api_app | 🟢 `_resolve_api_credentials()` падает на settings; RuntimeError ловится общим `except Exception` |
| FloodWait | 🟡 FloodWait ловится внутри async-функции (строка 177) и **никогда не доходит** до Celery `autoretry_for=(FloodWait,)` — autoretry фактически мёртвый код |
| Сетевые ошибки | 🟢 Общий `except Exception` на строках 245 и 256, логируется в dispatch_log + Sentry |
| Retry логика | 🔴 Celery autoretry на FloodWait = мёртвый код. Сетевые ошибки **не ретраятся** — задача просто завершается |
| Зависание | 🔴 **Нет `time_limit` / `soft_time_limit`.** Цикл по контактам с `asyncio.sleep(40-120с)` между каждым. Для 100 контактов = 67-200 минут. Задача может работать **часами** |
| DB-сессия | 🔴 `SessionLocal()` открыта **весь цикл** (часы). Держит DB-соединение из пула (pool_size=20+5) |
| Pyrogram-клиент | 🟢 `async with client:` — корректно закрывается |

---

## 2. `account_health_check` — tasks.py:289

| Критерий | Статус |
|---|---|
| Модель | 🟡 Legacy `Account` (TODO на строке 295) |
| Fallback без api_app | 🟢 Через `_resolve_api_credentials()` |
| FloodWait | 🟢 Ловится на строке 329, устанавливает cooldown |
| Сетевые ошибки | 🟡 Общий `except Exception` (строка 331) логирует на уровне **`info`**, не `error`. **Нет Sentry capture** |
| Retry логика | 🔴 Нет retry вообще (`@celery_app.task` без параметров) |
| Зависание | 🟡 Нет time_limit, но операция быстрая (один `get_me()`) |
| DB-сессия | 🟢 `with SessionLocal()` — корректно |
| Pyrogram-клиент | 🟢 `async with client:` — корректно |

---

## 3. `start_warming` — tasks.py:445

| Критерий | Статус |
|---|---|
| Модель | 🟡 Legacy `Account` (TODO на строке 354) |
| Fallback без api_app | 🟢 Через `_resolve_api_credentials()` |
| FloodWait | 🟡 Celery `autoretry_for=(FloodWait,)` — **мёртвый код** (FloodWait ловится внутри на строке 416). Внутренний обработчик ставит cooldown ✅ |
| Сетевые ошибки | 🟢 Общий `except Exception` (строка 425) + Sentry |
| Retry логика | 🔴 Celery autoretry = мёртвый код. Реальных retries нет |
| Зависание | 🔴 **Нет `time_limit`.** `perform_low_risk_action()` содержит `asyncio.sleep(60-300с)` на каждое действие. При target_actions=10 и 3-8 под-действий = **от 30 минут до 6+ часов** |
| DB-сессия | 🔴 `SessionLocal()` открыта **весь warming цикл** (часы) |
| Pyrogram-клиент | 🟢 `async with client:` — корректно |

---

## 4. `perform_warming_action` — tasks.py:456

| Критерий | Статус |
|---|---|
| Общая оценка | 🟡 **Пустая задача / dead code.** Только логирует сообщение. Нет реальной логики |

---

## 5. `check_cooldowns` — tasks.py:462

| Критерий | Статус |
|---|---|
| Модель | 🟡 Legacy `Account` (TODO на строке 466) |
| FloodWait | N/A — нет Telegram API вызовов |
| Сетевые ошибки | 🔴 **Нет обработки исключений вообще.** Если DB-запрос или `db.commit()` упадёт — задача крашится |
| Retry логика | 🔴 Нет retry |
| Зависание | 🟢 Быстрая задача, низкий риск |
| DB-сессия | 🟢 `with SessionLocal()` — корректно |

---

## 6. `sync_3proxy_config` — tasks.py:490

| Критерий | Статус |
|---|---|
| FloodWait | N/A |
| Сетевые ошибки | 🔴 **Нет обработки исключений.** `sync_3proxy()` содержит `subprocess.check_call()` — может кинуть `CalledProcessError` или зависнуть |
| Retry логика | 🔴 Нет retry |
| Зависание | 🔴 `subprocess.check_call()` в `sync_3proxy()` (proxy_sync.py:52) вызывается **без timeout**. Если команда зависнет — задача зависнет навсегда |
| DB-сессия | 🟢 `with SessionLocal()` внутри `sync_3proxy()` — корректно, закрывается быстро |

---

## 7. `validate_proxy_task` — tasks.py:496

| Критерий | Статус |
|---|---|
| FloodWait | 🟡 Не обрабатывается отдельно. FloodWait при `get_me()` попадёт в общий `except Exception` и пометит прокси как error. Некритично, но неточно |
| Сетевые ошибки | 🟡 Общий `except Exception` внутри `validate_proxy()` — ловит и ставит proxy.status=error. Но `TelegramClientDisabledError` **re-raise** (proxy_validation.py:23) и не обрабатывается на уровне Celery-задачи |
| Retry логика | 🔴 Нет retry |
| Зависание | 🟡 Нет time_limit, но `async with client: get_me()` — обычно быстро |
| DB-сессия | 🟢 `with SessionLocal()` — корректно |
| Pyrogram-клиент | 🟢 `async with client:` — корректно |

---

## 8. `legacy_verify_account` — tasks.py:502

| Критерий | Статус |
|---|---|
| Модель | 🟡 Legacy `Account` (TODO на строке 513) |
| Fallback без api_app | 🟢 Через `_resolve_api_credentials()` |
| FloodWait | 🟢 Ловится на строке 536, cooldown + метрики + лог |
| Сетевые ошибки | 🟢 Общий `except Exception` (строка 546) с `logger.exception()` (traceback) |
| Retry логика | 🔴 Нет retry на уровне Celery |
| Зависание | 🟡 Нет time_limit, но операция простая (get_me) |
| DB-сессия | 🟢 `with SessionLocal()` — корректно |
| Pyrogram-клиент | 🟢 `async with client:` — корректно |

---

## 9. `send_code_task` — tg_auth_tasks.py:375

| Критерий | Статус |
|---|---|
| Модель | 🟢 `TelegramAccount` |
| FloodWait | 🟢 Ловится на строке 337, `_handle_floodwait()` + метрики |
| Сетевые ошибки | 🟢 Общий `except Exception` (строка 346) с `_is_network_error()` — помечает прокси unhealthy |
| Retry логика | 🔴 **`max_retries=2, bind=True` объявлено, но `self.retry()` нигде не вызывается.** Все исключения ловятся внутри `_run_send_code()` и обрабатываются там. Retry config = мёртвый код |
| Зависание | 🟡 Нет time_limit, но операция относительно быстрая |
| DB-сессия | 🟢 `with SessionLocal()` — корректно |
| Pyrogram-клиент | 🟢 `finally: await client.disconnect()` — корректно |

---

## 10. `confirm_code_task` — tg_auth_tasks.py:630

| Критерий | Статус |
|---|---|
| Модель | 🟢 `TelegramAccount` |
| FloodWait | 🟢 Ловится на строке 594 |
| Сетевые ошибки | 🟢 Общий `except Exception` (строка 601) + `_is_network_error()` |
| Retry логика | 🔴 **`max_retries=1, bind=True` объявлено, но `self.retry()` нигде не вызывается.** Мёртвый код |
| Зависание | 🟡 Нет time_limit |
| DB-сессия | 🟢 `with SessionLocal()` — корректно |
| Pyrogram-клиент | 🟢 `finally: await client.disconnect()` — корректно |

---

## 11. `confirm_password_task` — tg_auth_tasks.py:782

| Критерий | Статус |
|---|---|
| Модель | 🟢 `TelegramAccount` |
| FloodWait | 🟢 Ловится на строке 744 |
| Сетевые ошибки | 🟢 Общий `except Exception` (строка 754) + `_is_network_error()` |
| Retry логика | 🔴 **`max_retries=1, bind=True` объявлено, но `self.retry()` нигде не вызывается.** Мёртвый код |
| Зависание | 🟡 Нет time_limit |
| DB-сессия | 🟢 `with SessionLocal()` — корректно |
| Pyrogram-клиент | 🟢 `finally: await client.disconnect()` — корректно |

---

## 12. `verify_account_task` — tg_auth_tasks.py:934

| Критерий | Статус |
|---|---|
| Модель | 🟢 `TelegramAccount` |
| FloodWait | 🟢 Ловится на строке 893, `_handle_floodwait()` |
| Сетевые ошибки | 🟢 Общий `except Exception` (строка 905) + `_is_network_error()` + proxy unhealthy |
| Retry логика | 🔴 **`max_retries=2, default_retry_delay=5, bind=True` объявлено, но `self.retry()` нигде не вызывается.** Все исключения ловятся внутри, lease release + status update. Retry config = мёртвый код |
| Зависание | 🟡 Нет time_limit, но операция простая |
| Lease management | 🟢 `acquire_verify_lease` / `release_verify_lease` в каждой ветке + `active_verifications.dec()` в `finally` |
| DB-сессия | 🟢 `with SessionLocal()` — корректно |
| Pyrogram-клиент | 🟢 `finally: await client.disconnect()` — корректно |

---

## 13. `_redis_ws_subscriber` — main.py:148

| Критерий | Статус |
|---|---|
| Ошибки | 🟢 `CancelledError` — graceful stop. Общие ошибки — reconnect с exponential backoff (1с → 30с) |
| Зависание | 🟢 Reconnect логика предотвращает зависание |
| Redis connection | 🟢 `finally:` блок закрывает pubsub и Redis-клиент |
| Утечка памяти | 🟢 Ссылка сохранена в `app.state.ws_subscriber_task` — GC не соберёт |

---

## 14. `_ping_loop` — main.py:536

| Критерий | Статус |
|---|---|
| Ошибки | 🟢 `except Exception: pass` — намеренно, т.к. отменяется в `finally` блоке WebSocket handler |
| Зависание | 🟢 Привязан к жизни WebSocket-соединения, отменяется при disconnect |

---

## Connection Management

### DB-сессии (SessionLocal)

| Задача | Проблема |
|---|---|
| 🟢 Все задачи | Используют `with SessionLocal() as db:` — автоматическое закрытие |
| 🔴 `campaign_dispatch` | Сессия удерживается **весь цикл рассылки** (часы). Может исчерпать pool (20+5=25 max) |
| 🔴 `start_warming` | Сессия удерживается **весь warming цикл** (часы). Та же проблема с пулом |
| 🟡 Глобальная конфигурация | Нет `task_time_limit` / `task_soft_time_limit` в Celery config — ни одна задача не ограничена по времени |

### Pyrogram-клиенты

| Задача | Статус |
|---|---|
| 🟢 tasks.py | `async with client:` — все клиенты закрываются корректно |
| 🟢 tg_auth_tasks.py | `finally: await client.disconnect()` — все клиенты закрываются корректно |
| 🟢 proxy_validation.py | `async with client:` — корректно |

### Redis connections

| Проблема | Статус |
|---|---|
| 🟡 `broadcast_sync` → `_publish_to_redis` | Создаёт **новый Redis-клиент** на каждый вызов (`Redis.from_url()`). В `campaign_dispatch` вызывается на каждый контакт. При 100 контактах = 100+ Redis-подключений за одну задачу. Нет пула |
| 🟡 Heartbeat thread | Redis-клиент (`Redis.from_url()`) создаётся один раз, но **никогда не закрывается** явно. Утечка при shutdown |

### Connection pool exhaustion

🔴 **При `CELERY_CONCURRENCY > 1` и параллельных campaign_dispatch / start_warming задачах:**
- Каждая задача держит DB-соединение часами
- Pool = 20 соединений + 5 overflow = 25 max
- 25+ параллельных длинных задач → `pool timeout` и отказ новых задач

---

## Задачи которые могут молча упасть

| Задача | Проблема |
|---|---|
| 🔴 `check_cooldowns` | Нет `try/except` вообще. DB ошибка → необработанное исключение. Celery залогирует, но нет Sentry / алертов |
| 🔴 `sync_3proxy_config` | Нет `try/except`. `subprocess.check_call` → `CalledProcessError` или бесконечное зависание |
| 🟡 `account_health_check` | Общая ошибка логируется как `logger.info` (строка 332), нет `sentry_sdk.capture_exception`. В production с уровнем WARNING+ — будет потеряна |
| 🟡 `validate_proxy_task` | `TelegramClientDisabledError` re-raised из `validate_proxy()` (proxy_validation.py:23) — необработанная на уровне Celery task |
| 🔴 `send_code_task` | Retry config (`max_retries=2`) — мёртвый код, `self.retry()` не вызывается |
| 🔴 `confirm_code_task` | Retry config (`max_retries=1`) — мёртвый код |
| 🔴 `confirm_password_task` | Retry config (`max_retries=1`) — мёртвый код |
| 🔴 `verify_account_task` | Retry config (`max_retries=2`) — мёртвый код |

---

## Итоговая сводка

### 🔴 Критические проблемы (6)

1. **Нет `time_limit` ни на одной задаче и в глобальном конфиге Celery.** `campaign_dispatch` и `start_warming` могут работать часами, блокируя worker
2. **DB-сессия удерживается часами** в `campaign_dispatch` и `start_warming` — угроза connection pool exhaustion
3. **`sync_3proxy_config`**: `subprocess.check_call()` без timeout — может зависнуть навсегда
4. **`check_cooldowns`**: нет обработки исключений вообще
5. **Celery retry config мёртвый код** в 4 задачах tg_auth_tasks.py — `max_retries`/`bind=True` объявлено, но `self.retry()` не вызывается; `autoretry_for` в tasks.py не срабатывает (исключения ловятся внутри)
6. **Нет retry для network errors** ни в одной задаче tasks.py (кроме мёртвого autoretry)

### 🟡 Предупреждения (5)

1. **Все 6 задач в tasks.py используют legacy `Account`** вместо `TelegramAccount` (помечено TODO)
2. **`account_health_check`**: ошибки логируются как `info`, нет Sentry capture
3. **`validate_proxy_task`**: `TelegramClientDisabledError` не обрабатывается на уровне задачи
4. **`broadcast_sync`**: создаёт новый Redis-клиент на каждый вызов — неэффективно при массовой рассылке
5. **`perform_warming_action`**: мёртвый код (пустая задача)

### 🟢 Хорошо реализовано (4)

1. **tg_auth_tasks.py**: Все 4 задачи имеют полную обработку FloodWait, сетевых ошибок, метрики, Sentry
2. **Pyrogram-клиенты**: Корректно закрываются во всех задачах
3. **`_redis_ws_subscriber`**: Устойчив к ошибкам с exponential backoff reconnect
4. **Lease-based idempotency** в `verify_account_task`: предотвращает дублирование
