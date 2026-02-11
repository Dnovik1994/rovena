# Telegram account connection flow (MTProto + WebApp auth)

## Scope

This document describes **two independent flows** found in the repository:

1. **Telegram Mini App user login** (`/auth/telegram`) using WebApp `initData` validation with bot token.
2. **Telegram account connection** (`/tg-accounts/*`) using **Pyrogram MTProto** (phone → code → optional 2FA password), with encrypted `StringSession` persistence.

## Technologies in use

- MTProto client library: **Pyrogram** (`pyrogram==2.0.106`, `tgcrypto==1.2.5`).
- Telegram account client class: `pyrogram.Client`.
- WebApp auth (Bot token signature check): HMAC validation of Telegram `initData`.

No Telethon/TDLib/login-widget SDK code was found in backend runtime paths.

## Entry points (UI + API)

### UI for MTProto account connection

`frontend/src/pages/Accounts.tsx`:
- Add account (phone in E.164).
- Send code.
- Confirm code.
- Confirm 2FA password.
- Poll auth-flow status and receive WS updates.
- Disconnect account.

### API endpoints for MTProto account connection

Router prefix: `/api/v1` + `/tg-accounts`.

- `POST /tg-accounts` — create account record (phone).
- `POST /tg-accounts/{account_id}/send-code` — create auth flow + enqueue worker.
- `GET /tg-accounts/{account_id}/auth-flow/{flow_id}` — poll flow status.
- `POST /tg-accounts/{account_id}/confirm-code` — enqueue code verification.
- `POST /tg-accounts/{account_id}/confirm-password` — enqueue 2FA verification.
- `POST /tg-accounts/{account_id}/disconnect` — local disconnect (clear stored session).

### API endpoint for WebApp user login

- `POST /auth/telegram` — validate WebApp `initData` using bot token, issue app JWT pair.

## MTProto flow (phone → code → 2FA)

### Step 1 — register phone locally

1. Frontend submits phone (`+E164`) to `POST /tg-accounts`.
2. Backend validates uniqueness per owner and tariff limits.
3. Creates `telegram_accounts` row with `status=new`.

### Step 2 — request code

1. Frontend calls `POST /tg-accounts/{id}/send-code`.
2. Backend ensures account status is one of: `new|code_sent|error|disconnected`.
3. Backend expires previous active flows and creates `telegram_auth_flows` row:
   - `state=init`
   - `expires_at=now + AUTH_FLOW_TTL_SECONDS`
4. Backend enqueues Celery `send_code_task(account_id, flow_id)`.
5. Worker:
   - creates Pyrogram client (`create_tg_account_client`)
   - `connect()`
   - `send_code(phone)`
   - stores `phone_code_hash` into `flow.meta_json`
   - updates flow to `wait_code`, account to `code_sent`
   - broadcasts WS updates.

### Step 3 — submit OTP code

1. Frontend calls `POST /tg-accounts/{id}/confirm-code` with `{flow_id, code}`.
2. Backend checks flow state, expiry, attempt limits, then enqueues `confirm_code_task`.
3. Worker:
   - increments flow attempts
   - creates client and `connect()`
   - tries to re-send code to refresh context (best-effort)
   - calls `sign_in(phone_number, phone_code_hash, phone_code)`.

Outcomes:
- **Success**: exports session string, encrypts and stores in `telegram_accounts.session_encrypted`; fills Telegram profile fields; account `verified`; flow `done`.
- **2FA required** (`SessionPasswordNeeded`): account `password_required`, flow `wait_password`, extends flow TTL, stores partial session for continuation.
- **Invalid/expired/flood**: updates `last_error`; on severe errors marks `error/failed/expired` states.

### Step 4 — submit 2FA password (if required)

1. Frontend calls `POST /tg-accounts/{id}/confirm-password` with `{flow_id, password}`.
2. Backend validates state/expiry/attempts and enqueues `confirm_password_task`.
3. Worker:
   - creates client (using saved encrypted session)
   - `connect()`
   - `check_password(password)`
   - exports/encrypts final session string
   - `get_me()` and persists profile fields
   - sets account `verified`, flow `done`.

## Session creation and storage

- Session type: **Pyrogram StringSession** (`export_session_string()`).
- Stored only as encrypted value in DB column `telegram_accounts.session_encrypted`.
- Encryption: **AES-256-GCM** via `SESSION_ENC_KEY` (env/config), nonce+ct base64.
- On client creation, if `session_encrypted` exists, it is decrypted and passed as `session_string` into `pyrogram.Client`.

No SQLite `.session` files are used in this flow (`in_memory=True` default for auth clients).

## State machine

### Account statuses (`telegram_accounts.status`)

`new`, `code_sent`, `password_required`, `verified`, `disconnected`, `error`, `banned`, `warming`, `active`, `cooldown`.

### Auth flow statuses (`telegram_auth_flows.state`)

`init`, `code_sent`, `wait_code`, `wait_password`, `done`, `expired`, `failed`.

Note: in runtime worker logic the primary transitional success state is `wait_code`; `code_sent` exists in enum and accepted by some checks/polling logic.

## Error handling highlights

Handled explicitly in workers:

- `PhoneNumberInvalid` → flow/account marked failed/error.
- `PhoneCodeInvalid` → `last_error` set, flow remains active until attempts/expiry rules trigger terminal state.
- `PhoneCodeExpired` → flow `expired`, account `error`.
- `SessionPasswordNeeded` → transition to password step.
- `BadRequest` with `PASSWORD_HASH_INVALID` → invalid 2FA password.
- `FloodWait` → error with retry-after seconds in message.
- generic exceptions sanitized (`_sanitize_error`) to mask phone numbers in logs.

Additional protections:
- API rate limits (`3/min` send code, `5/min` confirm endpoints).
- max attempts (`AUTH_FLOW_MAX_ATTEMPTS`, default 5).
- flow TTL (`AUTH_FLOW_TTL_SECONDS`, default 300s).
- stale `init` flow auto-timeout by polling endpoint (~60s watchdog for worker pickup issue).

## Disconnect/revoke behavior

`POST /tg-accounts/{id}/disconnect` performs **local disconnect only**:
- sets status `disconnected`
- clears `session_encrypted`
- clears `last_error`

No explicit Telegram-side `log_out()` / session revocation / “terminate other sessions” call was found.

## WebApp auth (Bot token) vs MTProto account connect

### WebApp login

- Uses `TELEGRAM_BOT_TOKEN` to verify `initData` signature (`/auth/telegram`).
- Optional replay TTL check: `TELEGRAM_AUTH_TTL_SECONDS` against `auth_date`.
- Creates/updates local app `User`; returns app JWT access + refresh tokens.

### MTProto account connect

- Uses `TELEGRAM_API_ID` + `TELEGRAM_API_HASH` with Pyrogram `Client`.
- Executes phone/code/2FA authentication and stores encrypted StringSession.

These flows are separate and use different credentials.

## Environment variables involved

- `TELEGRAM_BOT_TOKEN` — WebApp initData signature validation.
- `TELEGRAM_AUTH_TTL_SECONDS` — initData freshness enforcement.
- `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` — MTProto client credentials.
- `SESSION_ENC_KEY` — encryption key for stored StringSession.
- `AUTH_FLOW_TTL_SECONDS` — OTP/2FA flow TTL.
- `AUTH_FLOW_MAX_ATTEMPTS` — max attempts per flow.

## Re-auth / lifecycle notes

- Re-auth is manual: start a new flow (`send-code`) when account is `new|code_sent|error|disconnected`.
- Existing encrypted session is reused automatically by `create_tg_account_client` when present.
- No explicit long-term session expiration policy is implemented in app code; practical validity depends on Telegram session lifecycle and whether the session gets revoked externally.
