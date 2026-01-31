#!/bin/sh
set -e

CONFIG_DIR=/etc/3proxy
CONFIG_FILE="$CONFIG_DIR/3proxy.cfg"
DEFAULT_CONFIG=/defaults/3proxy.cfg

mkdir -p "$CONFIG_DIR"

if [ ! -s "$CONFIG_FILE" ]; then
  cp "$DEFAULT_CONFIG" "$CONFIG_FILE"
  chmod 644 "$CONFIG_FILE"
fi

if [ "$#" -eq 0 ]; then
  set -- /usr/local/bin/3proxy "$CONFIG_FILE"
fi

exec "$@"
