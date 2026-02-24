# ROVENA: Диагностика готовности к 50 аккаунтам

**Дата:** 2026-02-24
**Текущее состояние:** ~3 аккаунта
**Целевое состояние:** 50 аккаунтов (прогрев + инвайт одновременно)

---

## 🔴 КРИТИЧНЫЕ ПРОБЛЕМЫ (блокеры масштабирования)

### 1. Celery worker: solo pool + concurrency=1 — полная сериализация задач

**Файл:** `docker-compose.prod.yml:234,242` и `.env.example:66-67`

```
CELERY_POOL=solo
CELERY_CONCURRENCY=1
```

**Проблема:** Solo pool выполняет задачи строго последовательно, одну за другой. При 50 аккаунтах каждый прогрев (`start_tg_warming`) занимает до 90 минут (soft_time_limit=5400s). Invite dispatch — до 5 минут. Единственный worker с concurrency=1 создаст очередь из сотен задач с задержкой в часы.

**Расчёт:** 50 аккаунтов × 1 warming task ≈ 50 задач. Каждая ~30 минут = 25 часов на один цикл прогрева (при concurrency=1). А `resume_tg_warming` запускается каждые 5 минут, наращивая бэклог.

**Важный нюанс:** Solo pool — единственный вариант, полностью совместимый с `asyncio.run()` внутри задач. Prefork создаёт дочерние процессы, в которых `asyncio.run()` работает корректно, но потребляет больше RAM. Gevent/eventlet конфликтуют с asyncio event loop.

**Fix:**
```yaml
# docker-compose.prod.yml — worker
CELERY_POOL: ${CELERY_POOL:-prefork}
CELERY_CONCURRENCY: ${CELERY_CONCURRENCY:-8}
```
С prefork каждый воркер-процесс — отдельный Python-процесс со своим event loop, `asyncio.run()` работает без проблем. При concurrency=8 и 512MB лимите RAM может быть мало — нужно увеличить до 4-6 GB.

**Альтернатива:** Запустить несколько реплик worker с solo pool:
```yaml
worker:
  deploy:
    replicas: 8
    resources:
      limits:
        memory: 1g
```

---

### 2. Worker memory limit 512MB — OOM при множественных Pyrogram клиентах

**Файл:** `docker-compose.prod.yml:223-226`

```yaml
worker:
  deploy:
    resources:
      limits:
        memory: 512m
```

**Проблема:** Каждый Pyrogram клиент потребляет 50-80MB RAM (TCP-соединение + crypto + буферы). При prefork/concurrency=8 и 8 одновременных Pyrogram клиентах: 8 × 80MB = 640MB только на клиенты + Python runtime + Celery overhead ≈ 1.2-1.5GB.

При solo pool с replicas=8: каждая реплика = 1 клиент × 80MB + Python ~100MB = 180-250MB, но 8 реплик × 250MB = 2GB суммарно.

**Fix:**
```yaml
worker:
  deploy:
    resources:
      limits:
        memory: 4g  # для prefork c concurrency=8
        # или
        memory: 512m  # для solo pool с replicas=8
```

**Ресурсы хоста:** 21GB RAM доступно, 16 CPU — ресурсов достаточно.

---

### 3. warming_max_concurrent=5 — жёсткий лимит на прогрев

**Файл:** `backend/app/core/settings.py:70`

```python
warming_max_concurrent: int = 5
```

**Файл:** `backend/app/workers/tg_warming_tasks.py:768`

```python
.limit(_get_max_concurrent())  # = 5
```

**Проблема:** `resume_tg_warming` (beat, каждые 5 минут) запрашивает из БД максимум 5 аккаунтов в статусе `warming` и отправляет `start_tg_warming.delay()`. При 50 аккаунтах: за каждый цикл beat только 5 получат задачу. При warming cycle ~30 минут, throughput = 5 × (60/30) = 10 аккаунтов/час. Для 50 аккаунтов full cycle = 5+ часов.

**Fix:** Добавить в `.env`:
```
WARMING_MAX_CONCURRENT=25
```
Или увеличить в коде default до 25-30 для 50 аккаунтов.

---

### 4. SQLAlchemy pool_size=20, max_overflow=5 — недостаточно для 50 параллельных задач

**Файл:** `backend/app/core/database.py:22-29`

```python
pool_size=20, max_overflow=5  # total max = 25 connections
```

**Проблема:** Каждая задача Celery открывает множество DB сессий (invite dispatch — 10+ сессий за задачу через `SessionLocal()`). При concurrency=8 воркеров × несколько сессий на задачу = легко превысить 25 соединений. `pool_timeout=30` → задачи будут ждать свободного соединения и тормозить.

Дополнительно: backend (FastAPI) использует тот же engine с pool_size=20, то есть API-запросы конкурируют с worker за одни и те же лимиты. НО — backend и worker это разные контейнеры, значит у каждого свой пул. Всё равно worker может исчерпать 25 соединений.

**Fix:**
```python
# database.py
engine_kwargs.update({
    "pool_size": 30,
    "max_overflow": 20,  # total max = 50 connections
})
```
А на стороне MySQL увеличить `max_connections` (по умолчанию 151 — должно хватить, но проверить).

---

### 5. MySQL memory limit 1GB — может не хватить при нагрузке

**Файл:** `docker-compose.prod.yml:117-119`

```yaml
db:
  deploy:
    resources:
      limits:
        memory: 1g
```

**Проблема:** MySQL 8.4 с дефолтной конфигурацией (без my.cnf customization) потребляет ~400-600MB idle. При 50 параллельных соединениях + SELECT FOR UPDATE + batch INSERT → пиковое потребление может превысить 1GB → OOM kill.

**Fix:** Увеличить лимит до 2GB и добавить custom my.cnf:
```yaml
db:
  deploy:
    resources:
      limits:
        memory: 2g
  volumes:
    - mysql-data:/var/lib/mysql
    - ./my.cnf:/etc/mysql/conf.d/custom.cnf:ro
```

```ini
# my.cnf
[mysqld]
max_connections = 200
innodb_buffer_pool_size = 512M
innodb_log_file_size = 128M
tmp_table_size = 64M
max_heap_table_size = 64M
```

---

### 6. Redis memory limit 256MB — может быть исчерпан

**Файл:** `docker-compose.prod.yml:141-143`

```yaml
redis:
  deploy:
    resources:
      limits:
        memory: 256m
```

**Проблема:** Redis используется как:
- Celery broker (очередь задач)
- Celery result backend (результаты задач)
- Heartbeat worker (TTL keys)
- WebSocket pub/sub
- Warming throttle (flood counters)
- Sync locks (Redis SET NX)
- Кэш пользователей

При 50 аккаунтах количество задач и результатов в Redis существенно вырастет. Нет `maxmemory-policy` — Redis будет расти до OOM kill без graceful eviction.

**Критично:** Celery result backend хранит результаты задач по умолчанию 24 часа. При сотнях задач/час → утечка памяти.

**Fix:**
```yaml
redis:
  command: redis-server --requirepass ${REDIS_PASSWORD} --maxmemory 512mb --maxmemory-policy allkeys-lru
  deploy:
    resources:
      limits:
        memory: 768m
```
Также добавить в Celery config:
```python
celery_app.conf.update(
    result_expires=3600,  # TTL результатов = 1 час вместо 24
)
```

---

## 🟡 СЕРЬЁЗНЫЕ ПРОБЛЕМЫ (риски)

### 7. Invite dispatch — последовательная обработка аккаунтов

**Файл:** `backend/app/workers/tg_invite_tasks.py:251`

```python
for acct_id in account_ids:  # последовательный цикл
```

**Проблема:** `invite_campaign_dispatch` обрабатывает аккаунты последовательно в одной задаче. Для каждого аккаунта: открывает Pyrogram клиент, инвайтит пользователей, ждёт sleep между инвайтами. При 50 аккаунтах × 10 инвайтов × 5 секунд sleep = ~2500 секунд = 42 минуты. Soft time limit = 300s → задача упадёт по таймауту.

**Вероятность:** Высокая при max_accounts > 5.

**Fix:** Разбить dispatch на отдельные задачи per-account:
```python
# Вместо цикла в одной задаче:
for acct_id in account_ids:
    invite_account_batch.delay(campaign_id, acct_id)
```

---

### 8. Trusted conversation создаёт ВТОРОЙ Pyrogram клиент внутри warming

**Файл:** `backend/app/workers/tg_warming_actions.py:163-194`

```python
async def _action_trusted_conversation(client, account, db, **kwargs) -> bool:
    ...
    client_trusted = create_tg_account_client(trusted, proxy, ...)
    async with client_trusted:  # второй клиент параллельно!
```

**Проблема:** Во время warming у нас уже есть один Pyrogram клиент. `_action_trusted_conversation` создаёт второй для trusted-аккаунта. При 25 параллельных warming задачах = 25 основных клиентов + до 25 trusted клиентов = 50 одновременных TCP-соединений к Telegram + 50 × 80MB RAM.

**Вероятность:** Средняя (action вызывается на день 3).

**Fix:** Ограничить количество одновременных trusted conversations через Semaphore или Redis lock.

---

### 9. Нет task routing — все задачи в одной очереди

**Файл:** `backend/app/workers/__init__.py:88-126`

Celery config не определяет `task_routes`. Все задачи (auth, warming, invite, sync, health check) попадают в одну очередь `celery`.

**Проблема:** Длинные warming задачи (до 90 минут) блокируют выполнение коротких задач (health check 30s, cooldown check 60s, cleanup 60s). При solo pool с concurrency=1 — health check может ждать 90 минут.

**Fix:**
```python
celery_app.conf.task_routes = {
    "app.workers.tg_warming_tasks.*": {"queue": "warming"},
    "app.workers.tg_invite_tasks.*": {"queue": "invite"},
    "app.workers.tg_sync_tasks.*": {"queue": "sync"},
    "app.workers.tg_auth_*": {"queue": "auth"},
    "app.workers.health_tasks.*": {"queue": "default"},
    "app.workers.warming_throttle.*": {"queue": "default"},
}
```
И запустить отдельные worker-инстансы для разных очередей.

---

### 10. Отсутствие retry policy на большинстве Celery задач

**Файлы:**
- `tg_invite_tasks.py:737-740` — `invite_campaign_dispatch`: нет retry
- `tg_warming_tasks.py:626-630` — `start_tg_warming`: нет retry
- `tg_campaign_tasks.py:245-249` — `parse_source_members`: нет retry
- `tg_sync_tasks.py:383` — `sync_account_data`: нет retry

**Проблема:** Если задача упадёт из-за transient error (сеть, Redis disconnect, MySQL timeout), она не будет повторена. При `task_acks_late=True` + `task_reject_on_worker_lost=True` — задача вернётся в очередь при SIGKILL, но не при exception.

**Вероятность:** Средняя — при масштабировании transient errors учащаются.

**Fix:** Добавить autoretry:
```python
@celery_app.task(
    bind=True,
    autoretry_for=(ConnectionError, TimeoutError, OperationalError),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=3,
)
```

---

### 11. InviteTask — нет индекса на status + campaign_id

**Файл:** `backend/app/models/invite_task.py`

Модель InviteTask имеет UniqueConstraint(`campaign_id`, `tg_user_id`), но нет составного индекса на (`campaign_id`, `status`), который используется в КАЖДОМ SELECT в invite dispatch:
```python
db.query(InviteTask).filter(
    InviteTask.campaign_id == campaign_id,
    InviteTask.status == InviteTaskStatus.pending,
).order_by(InviteTask.id.asc()).limit(batch_size)
.with_for_update(skip_locked=True)
```

**Проблема:** При тысячах InviteTask записей — full table scan на каждый SELECT FOR UPDATE.

**Fix:** Добавить миграцию:
```python
Index("ix_invite_task_campaign_status", "campaign_id", "status")
```

---

### 12. Device fingerprint — только Linux Desktop

**Файл:** `backend/app/clients/device_generator.py:3-15`

```python
DESKTOP_DEVICES = [
    {"device_model": "PC 64bit", "system_version": "Linux 5.15"},
    {"device_model": "PC 64bit", "system_version": "Linux 6.1"},
    # ... всё Linux
]
```

**Проблема:** Все 11 вариантов — Linux Desktop. Для Telegram это подозрительно: 50 аккаунтов с одного сервера, все на Linux. Telegram видит device_model + system_version + app_version + lang_code при каждом подключении.

**Вероятность:** Средняя — Telegram может ограничить аккаунты с идентичными fingerprints.

**Fix:** Добавить мобильные устройства и Windows:
```python
MOBILE_DEVICES = [
    {"device_model": "Samsung Galaxy S23", "system_version": "Android 14"},
    {"device_model": "iPhone 15", "system_version": "iOS 17.2"},
    {"device_model": "Xiaomi 13", "system_version": "Android 13"},
    # ...
]
WINDOWS_DEVICES = [
    {"device_model": "Desktop", "system_version": "Windows 10"},
    {"device_model": "Desktop", "system_version": "Windows 11"},
]
```
И привязать fingerprint к аккаунту (не генерировать при каждом создании клиента если нет сохранённого):
```python
device_config = getattr(account, "device_config", None) or generate_device_config()
```
Это уже сделано в `telegram_client.py:100,141` — fingerprint берётся из `account.device_config` если есть. Нужно только расширить пул устройств.

---

### 13. Warming task держит DB сессию всё время выполнения

**Файл:** `backend/app/workers/tg_warming_tasks.py:433-619`

```python
async def _run_tg_warming_cycle(account_id: int) -> None:
    db = SessionLocal()
    try:
        # ... вся работа на 30+ минут
    finally:
        db.close()
```

**Проблема:** Одна DB-сессия живёт до 90 минут (soft_time_limit). При 25 параллельных warming задачах = 25 долгоживущих соединений из пула. pool_size=20 + max_overflow=5 = 25 max. Все соединения заняты warming → другие задачи (invite, sync, beat) не смогут получить соединение.

**Вероятность:** Высокая при > 20 concurrent warming tasks.

**Fix:** Использовать паттерн `with SessionLocal() as db:` для каждой операции, как сделано в invite_tasks.py. Закрывать сессию после каждого action, а не держать открытой.

---

## 🟢 РЕКОМЕНДАЦИИ (оптимизация)

### 14. Pyrogram client lifecycle — корректная реализация

**Положительное:** Все worker-задачи используют `async with client:` для автоматического закрытия:
- `tg_invite_tasks.py:361` — `async with client:`
- `tg_warming_tasks.py:519` — `async with client:`
- `tg_campaign_tasks.py:86` — `async with client:`
- `tg_sync_tasks.py:186` — `async with client:`
- `tg_auth_unified_tasks.py:570-574` — явный `client.disconnect()` в finally

Session файлы хранятся в Docker volume `/data/pyrogram_sessions` с именами `tg-{account_id}` — конфликтов между клиентами не будет, каждый аккаунт имеет уникальное имя файла.

### 15. SELECT FOR UPDATE SKIP LOCKED — правильная защита от гонок

**Файл:** `tg_invite_tasks.py:294`

```python
.with_for_update(skip_locked=True)
```

Invite dispatch использует MySQL row-level locking с SKIP LOCKED — параллельные dispatch не возьмут одни и те же задачи.

### 16. Dispatch lease — защита от дублирования

**Файл:** `tg_invite_tasks.py:126-166`

Invite campaign dispatch использует lease через `dispatch_task_id` + `dispatch_started_at` с TTL=600s. Аналогично warming использует `acquire_warming_lease()` с atomic UPDATE.

### 17. Atomic increment — безопасные счётчики

**Файл:** `tg_invite_tasks.py:42-50`

```python
def _atomic_increment(db, campaign_id, field_name):
    field = getattr(InviteCampaign, field_name)
    db.execute(update(InviteCampaign).where(...).values({field_name: field + 1}))
```

Используется SQL-level `field + 1` вместо ORM read-modify-write — безопасно при параллельном доступе.

### 18. Warming throttle — адаптивное замедление

**Файл:** `backend/app/workers/warming_throttle.py`

Хорошая система: автоматически замедляет/приостанавливает прогрев при высоком проценте FloodWait (>8% → slow, >15% → paused). Это критично при 50 аккаунтах — одновременный FloodWait на всех может привести к массовому бану.

### 19. Orphan cleanup — очистка зависших задач

**Файл:** `tg_invite_tasks.py:779-800`

Периодическая задача `cleanup_orphan_invite_tasks` (каждые 10 минут) сбрасывает зависшие `in_progress` задачи обратно в `pending`. Хороший механизм resilience.

### 20. task_acks_late + task_reject_on_worker_lost — защита от потери задач

**Файл:** `backend/app/workers/__init__.py:94-95`

```python
task_acks_late=True,
task_reject_on_worker_lost=True,
```

При OOM kill worker'а задача вернётся в очередь. Правильная конфигурация.

### 21. Redis sync locks в sync tasks

**Файл:** `tg_sync_tasks.py:386-395`

```python
if not r.set(lock_key, self.request.id, ex=3600, nx=True):
    return  # another sync running
```

Использование Redis SET NX с TTL для предотвращения параллельного sync одного аккаунта — правильный подход.

### 22. Добавить monitoring dashboards в Grafana

Prometheus + Grafana уже настроены. Рекомендуется добавить дашборды для:
- Количество задач в очереди Celery по типу
- Активные warming/invite задачи
- FloodWait rate
- DB connection pool utilization
- Redis memory usage

### 23. Добавить Celery result_expires

**Файл:** `backend/app/workers/__init__.py:88-126`

В конфиге Celery нет `result_expires`. По умолчанию = 86400 (24 часа). При сотнях задач/день → сотни результатов занимают Redis RAM.

**Fix:**
```python
celery_app.conf.update(
    result_expires=3600,  # 1 час
)
```

---

## 📊 РЕСУРСНЫЙ ПЛАН

| Ресурс | Сейчас (3 акк.) | Нужно (50 акк.) | Статус |
|--------|------------------|-------------------|--------|
| **RAM (хост)** | 21 GB total, ~500MB used | ~8-10 GB used | ✅ Достаточно |
| **CPU (хост)** | 16 cores | 8-10 cores peak | ✅ Достаточно |
| **Worker RAM** | 512 MB limit | 4 GB (prefork×8) или 8×512MB (solo replicas) | 🔴 Увеличить |
| **Worker concurrency** | 1 (solo) | 8 (prefork) или 8 replicas | 🔴 Увеличить |
| **MySQL RAM** | 1 GB limit | 2 GB | 🟡 Увеличить |
| **MySQL max_connections** | 151 (default) | 200+ | 🟡 Настроить |
| **SQLAlchemy pool** | 20+5=25 | 30+20=50 | 🔴 Увеличить |
| **Redis RAM** | 256 MB limit | 512-768 MB | 🔴 Увеличить |
| **Redis maxmemory** | Не настроено | 512 MB + allkeys-lru | 🔴 Настроить |
| **Прокси** | ? (проверить в БД) | 50 (1:1) | 🟡 Проверить |
| **File descriptors** | 65535 (worker ulimit) | 65535 | ✅ Достаточно |
| **warming_max_concurrent** | 5 | 25-30 | 🔴 Увеличить |
| **Celery result_expires** | 86400s (default) | 3600s | 🟡 Уменьшить |
| **Task routing** | Одна очередь | 4-5 очередей | 🟡 Добавить |
| **Device fingerprints** | 11 вариантов (все Linux) | 30+ (Linux/Windows/Mobile) | 🟡 Расширить |

---

## 🗺️ ПЛАН ДЕЙСТВИЙ (в порядке приоритета)

### Этап 1: Критические фиксы (перед масштабированием)

1. **Увеличить worker concurrency**
   - Файл: `.env` → `CELERY_POOL=prefork`, `CELERY_CONCURRENCY=8`
   - Или: `docker-compose.prod.yml` → `worker.deploy.replicas: 8` с solo pool
   - Файл: `docker-compose.prod.yml` → worker `memory: 4g` (prefork) или `memory: 768m` (solo replicas)

2. **Увеличить warming_max_concurrent**
   - Файл: `.env` → `WARMING_MAX_CONCURRENT=25`

3. **Увеличить SQLAlchemy pool**
   - Файл: `backend/app/core/database.py:22-29`
   - `pool_size=30`, `max_overflow=20`

4. **Увеличить Redis лимиты**
   - Файл: `docker-compose.prod.yml:147`
   - `command: redis-server --requirepass ${REDIS_PASSWORD} --maxmemory 512mb --maxmemory-policy allkeys-lru`
   - `memory: 768m`

5. **Увеличить MySQL memory**
   - Файл: `docker-compose.prod.yml:117-119` → `memory: 2g`
   - Добавить custom `my.cnf` с `max_connections=200`

6. **Добавить result_expires в Celery**
   - Файл: `backend/app/workers/__init__.py:88` → добавить `result_expires=3600`

### Этап 2: Серьёзные улучшения

7. **Refactor warming DB session** — перейти на short-lived sessions
   - Файл: `backend/app/workers/tg_warming_tasks.py:433-619`
   - Заменить единственную `db = SessionLocal()` на `with SessionLocal() as db:` для каждой операции

8. **Добавить индекс на InviteTask(campaign_id, status)**
   - Создать Alembic миграцию

9. **Добавить task routing (очереди)**
   - Файл: `backend/app/workers/__init__.py` → `task_routes`
   - Файл: `docker-compose.prod.yml` → отдельные worker инстансы для очередей

10. **Добавить retry policy на задачи**
    - Файлы: все `*_tasks.py` → `autoretry_for`, `max_retries`, `retry_backoff`

11. **Расширить device fingerprints**
    - Файл: `backend/app/clients/device_generator.py`
    - Добавить Windows, Android, iOS варианты

### Этап 3: Оптимизация

12. **Параллелизировать invite dispatch по аккаунтам**
    - Файл: `backend/app/workers/tg_invite_tasks.py` → per-account subtasks

13. **Ограничить trusted conversation concurrency**
    - Файл: `backend/app/workers/tg_warming_actions.py:163`
    - Добавить Redis semaphore

14. **Проверить количество прокси в БД**
    - Для 50 аккаунтов нужно 50 прокси (1:1)
    - Проверить `UNIQUE(api_app_id, proxy_id)` constraint — хватит ли api_app-ов

15. **Добавить Grafana дашборды**
    - Celery queue depth, warming progress, FloodWait rate, DB pool utilization
