#!/bin/bash
# bt-reconnect — persistent watchdog that keeps the BT HID keyboard connected.
#
# Deploy to: /usr/local/bin/bt-reconnect
# Invoked by: /etc/systemd/system/bt-keyboard.service (Type=simple, Restart=always).
#
# Behavior:
#   - Runs forever as a watchdog loop.
#   - Every CHECK_INTERVAL seconds, checks if the device is connected.
#   - If disconnected, fires up to CONNECT_ATTEMPTS connect calls with short
#     delays, then backs off to CHECK_INTERVAL before retrying.
#   - Device is already paired + trusted + bonded; no pairing state is changed.

set -u

MAC="${BT_MAC:-D9:5C:95:0E:09:74}"
CHECK_INTERVAL="${BT_CHECK_INTERVAL:-10}"   # seconds between health checks
CONNECT_ATTEMPTS="${BT_CONNECT_ATTEMPTS:-5}" # tries per reconnect burst
CONNECT_WAIT="${BT_CONNECT_WAIT:-4}"        # seconds to wait after each connect call
INITIAL_DELAY="${BT_INITIAL_DELAY:-5}"      # startup grace period

echo "bt-reconnect: watchdog start target=${MAC}"

sleep "${INITIAL_DELAY}"

is_connected() {
    bluetoothctl info "${MAC}" 2>/dev/null | grep -qE '^\s*Connected:\s*yes\s*$'
}

reconnect_burst() {
    bluetoothctl power on  >/dev/null 2>&1 || true
    for i in $(seq 1 "${CONNECT_ATTEMPTS}"); do
        echo "bt-reconnect: attempt ${i}/${CONNECT_ATTEMPTS}"
        bluetoothctl connect "${MAC}" >/dev/null 2>&1 || true
        sleep "${CONNECT_WAIT}"
        if is_connected; then
            echo "bt-reconnect: connected on attempt ${i}"
            return 0
        fi
    done
    echo "bt-reconnect: burst exhausted, will retry in ${CHECK_INTERVAL}s"
    return 1
}

while true; do
    if ! is_connected; then
        echo "bt-reconnect: not connected, starting reconnect burst"
        reconnect_burst
    fi
    sleep "${CHECK_INTERVAL}"
done
