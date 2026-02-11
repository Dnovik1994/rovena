FROM alpine:3.20

RUN set -eux; \
    printf '%s\n' \
      'https://dl-cdn.alpinelinux.org/alpine/v3.20/main' \
      'https://dl-cdn.alpinelinux.org/alpine/v3.20/community' > /etc/apk/repositories; \
    attempts=0; \
    until [ "$attempts" -ge 5 ]; do \
      apk update && apk add --no-cache mariadb-client redis && break; \
      attempts=$((attempts + 1)); \
      sleep $((attempts * 2)); \
    done; \
    if [ "$attempts" -ge 5 ]; then \
      echo 'apk install failed after retries' >&2; \
      exit 1; \
    fi

CMD ["crond", "-f", "-l", "2"]
