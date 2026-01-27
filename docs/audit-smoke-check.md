# Smoke-check command log

## $ ls -la
```
total 96
drwxr-xr-x 8 root root 4096 Jan 27 12:09 .
drwxr-xr-x 3 root root 4096 Jan 27 11:59 ..
-rw-r--r-- 1 root root  917 Jan 27 12:12 .env.example
drwxr-xr-x 8 root root 4096 Jan 27 12:14 .git
drwxr-xr-x 3 root root 4096 Jan 27 11:59 .github
-rw-r--r-- 1 root root    0 Jan 27 11:59 .gitkeep
-rw-r--r-- 1 root root   80 Jan 27 11:59 3proxy.cfg
-rw-r--r-- 1 root root 9018 Jan 27 12:12 README.md
-rw-r--r-- 1 root root  831 Jan 27 12:09 RELEASE_NOTES.md
drwxr-xr-x 5 root root 4096 Jan 27 12:09 backend
-rw-r--r-- 1 root root   56 Jan 27 11:59 blackbox.yml
-rw-r--r-- 1 root root  139 Jan 27 12:09 crontab.txt
-rw-r--r-- 1 root root 1062 Jan 27 11:59 docker-compose.override.yml
-rw-r--r-- 1 root root 4475 Jan 27 12:09 docker-compose.prod.yml
-rw-r--r-- 1 root root 2813 Jan 27 11:59 docker-compose.yml
drwxr-xr-x 2 root root 4096 Jan 27 12:09 docs
drwxr-xr-x 4 root root 4096 Jan 27 12:09 frontend
-rw-r--r-- 1 root root 2543 Jan 27 12:09 locustfile.py
-rw-r--r-- 1 root root 2819 Jan 27 12:09 nginx.conf
-rw-r--r-- 1 root root  718 Jan 27 11:59 prometheus.yml
-rw-r--r-- 1 root root  643 Jan 27 11:59 prometheus_rules.yml
drwxr-xr-x 2 root root 4096 Jan 27 11:59 scripts
```

## $ find . -maxdepth 2 -type f | sort
```
./.env.example
./.git/COMMIT_EDITMSG
./.git/FETCH_HEAD
./.git/HEAD
./.git/config
./.git/description
./.git/index
./.git/packed-refs
./.gitkeep
./3proxy.cfg
./README.md
./RELEASE_NOTES.md
./backend/Dockerfile
./backend/alembic.ini
./backend/requirements-dev.txt
./backend/requirements.txt
./blackbox.yml
./crontab.txt
./docker-compose.override.yml
./docker-compose.prod.yml
./docker-compose.yml
./docs/load_test.md
./docs/performance.md
./docs/security.md
./docs/technical-spec.md
./frontend/Dockerfile
./frontend/Dockerfile.dev
./frontend/index.html
./frontend/nginx.conf
./frontend/package.json
./frontend/postcss.config.js
./frontend/tailwind.config.js
./frontend/tsconfig.json
./frontend/vite.config.ts
./locustfile.py
./nginx.conf
./prometheus.yml
./prometheus_rules.yml
./scripts/dev-check.sh
./scripts/dev-clean.sh
./scripts/dev-up.sh
```

## $ git status -sb
```
## work
?? frontend/node_modules/
```

## $ git log --oneline -n 15
```
c4e574f Harden Telegram auth and error responses
4d08259 Merge pull request #2 from Dnovik1994/codex/implement-owasp-security-enhancements-and-jwt-refresh
5d6f9a3 Add onboarding flow and production hardening
d0877e5 Merge pull request #1 from Dnovik1994/codex/develop-telegram-mini-app-for-inviting
d8c6a51 Add Stripe subscription flow and UI polish
d47695a Initialize repository
```

## $ git branch --show-current
```
work
```

## $ docker compose config
```
/bin/sh: 1: docker: not found
```

## $ docker compose up -d --build
```
/bin/sh: 1: docker: not found
```

## $ docker compose ps
```
/bin/sh: 1: docker: not found
```

## $ docker compose logs --tail=200 backend
```
/bin/sh: 1: docker: not found
```

## $ docker compose exec backend alembic upgrade head
```
/bin/sh: 1: docker: not found
```

## $ curl -i http://localhost:8000/health
```
  % Total    % Received % Xferd  Average Speed   Time    Time     Time  Current
                                 Dload  Upload   Total   Spent    Left  Speed

  0     0    0     0    0     0      0      0 --:--:-- --:--:-- --:--:--     0
  0     0    0     0    0     0      0      0 --:--:-- --:--:-- --:--:--     0
curl: (7) Failed to connect to localhost port 8000 after 0 ms: Couldn't connect to server
```

## $ docker compose logs --tail=200 frontend
```
/bin/sh: 1: docker: not found
```

## $ docker compose exec frontend npm -v
```
/bin/sh: 1: docker: not found
```

## $ docker compose exec frontend npm run build
```
/bin/sh: 1: docker: not found
```
