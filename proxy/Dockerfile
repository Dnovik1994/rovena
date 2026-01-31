FROM alpine:3.20 AS builder

RUN apk add --no-cache build-base git openssl-dev

WORKDIR /tmp/3proxy
RUN git clone --depth 1 https://github.com/3proxy/3proxy.git . \
  && make -f Makefile.Linux

FROM alpine:3.20

RUN apk add --no-cache openssl

COPY --from=builder /tmp/3proxy/bin/3proxy /usr/local/bin/3proxy
COPY 3proxy.cfg /defaults/3proxy.cfg
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 755 /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
