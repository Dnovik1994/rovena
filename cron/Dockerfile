FROM alpine:3.20

RUN set -eux; \
    ok=0; \
    for i in 1 2 3 4 5; do \
      apk add --no-cache mariadb-client redis util-linux && ok=1 && break; \
      echo "Retry $i: apk install failed, waiting..." >&2; \
      sleep $((i * 5)); \
    done; \
    [ "$ok" = 1 ] || { echo 'apk install failed after retries' >&2; exit 1; }; \
    rm -rf /etc/periodic

# crond requires root for the daemon, but cron jobs run as cronuser
RUN adduser -D -s /bin/sh cronuser

CMD ["crond", "-f", "-l", "2"]
