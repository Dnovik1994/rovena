# Security Compliance Report (OWASP Top 10)

## Scope
Backend API, frontend Mini App, nginx proxy, and background workers.

## Summary
- **Authentication & session management**: short-lived access tokens and refresh rotation.
- **Input validation**: centralized sanitization and schema validation.
- **Transport & headers**: CSP/HSTS/XSS/CTO headers at app + nginx.
- **Access control**: RBAC and IP whitelist for admin.

## OWASP Checklist
1. **Broken Access Control** — Roles enforced in API, admin routes whitelisted by IP.
2. **Cryptographic Failures** — Refresh token stored hashed, JWT secrets via env.
3. **Injection** — Pydantic validators sanitize inputs and reject injection patterns.
4. **Insecure Design** — Rate limiting and CSRF guard (optional) configured.
5. **Security Misconfiguration** — Headers set at nginx and FastAPI.
6. **Vulnerable/Outdated Components** — Pin dependencies in `requirements.txt`/`package.json`.
7. **Identification & Auth Failures** — Access/refresh separation and rotation.
8. **Software & Data Integrity Failures** — CI should pin hashes for deps (recommended).
9. **Security Logging/Monitoring** — Sentry integration and structured logs.
10. **SSRF** — No direct user-controlled outbound fetches.

## Evidence
- Access/refresh token flow in `auth` handlers.
- Sanitized schema models in `backend/app/schemas`.
- Security headers in `main.py` and `nginx.conf`.

## Gaps / Follow-ups
- Enable TLS termination in production (Certbot + nginx).
- Add static analysis and dependency scans to CI.
