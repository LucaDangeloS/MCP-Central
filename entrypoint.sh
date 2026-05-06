#!/usr/bin/env bash
# MCP Central entrypoint
# 1. Generate tinyproxy config from env vars
# 2. Start tinyproxy
# 3. Run Alembic migrations
# 4. Start the hub

set -euo pipefail

echo "[entrypoint] Starting MCP Central..."

# ------------------------------------------------------------------ #
# 1. Generate tinyproxy config                                         #
# ------------------------------------------------------------------ #
TINYPROXY_CONF=/tmp/tinyproxy.conf
TINYPROXY_FILTER=/tmp/tinyproxy_blocked.txt
PROXY_PORT="${PROXY_PORT:-8888}"

# Write minimal tinyproxy config
cat > "$TINYPROXY_CONF" <<EOF
Port ${PROXY_PORT}
Listen 127.0.0.1
Timeout 30
LogLevel Error
DisableViaHeader Yes
Allow 127.0.0.1
EOF

# Append domain filter if BLOCKED_DOMAINS is set
if [ -n "${BLOCKED_DOMAINS:-}" ]; then
    echo "" >> "$TINYPROXY_CONF"
    echo "Filter \"${TINYPROXY_FILTER}\"" >> "$TINYPROXY_CONF"
    echo "FilterDefaultDeny No" >> "$TINYPROXY_CONF"
    echo "FilterExtended Yes" >> "$TINYPROXY_CONF"

    # Write domain filter file (one regex per line)
    > "$TINYPROXY_FILTER"
    IFS=',' read -ra DOMAINS <<< "${BLOCKED_DOMAINS}"
    for domain in "${DOMAINS[@]}"; do
        domain="$(echo "$domain" | tr -d ' ')"
        if [ -n "$domain" ]; then
            # Escape dots and anchor the pattern
            echo "^$(echo "$domain" | sed 's/\./\\\\./g')$" >> "$TINYPROXY_FILTER"
        fi
    done
    echo "[entrypoint] tinyproxy domain filter written ($(wc -l < "$TINYPROXY_FILTER") entries)"
fi

# ------------------------------------------------------------------ #
# 2. Start tinyproxy                                                   #
# ------------------------------------------------------------------ #
tinyproxy -d -c "$TINYPROXY_CONF" &
echo "[entrypoint] tinyproxy started on 127.0.0.1:${PROXY_PORT}"

# ------------------------------------------------------------------ #
# 3. Run Alembic migrations                                            #
# ------------------------------------------------------------------ #
echo "[entrypoint] Running database migrations..."
cd /app
python -m alembic upgrade head
echo "[entrypoint] Migrations complete."

# ------------------------------------------------------------------ #
# 4. Start the hub                                                     #
# ------------------------------------------------------------------ #
echo "[entrypoint] Starting hub on internal port 8000..."
exec python -m uvicorn hub.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --no-access-log
