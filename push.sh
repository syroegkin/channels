#!/usr/bin/env bash
# Build the client and push it directly into the Spectrum's RAM via Spectranet ethup.
#
# Prereqs (one-time):
#   1. ethup installed on this host — see spectrumero/spectranet repo, tools/ethup/
#      (build with `make` inside that dir, then `sudo cp ethup /usr/local/bin/`)
#   2. Spectrum has Spectranet cartridge on the same LAN as this host
#   3. Know your Spectrum's IP (set it via env or arg; we'll try to remember it)
#
# Each push (~2–3 seconds total vs reflashing):
#   1. On Spectrum: `CLEAR 24999` once per session
#   2. On Spectrum: press NMI button → "Load arbitrary data..."
#   3. On host: `./push.sh <spectrum-ip>`
#   4. On Spectrum: exit NMI menu → `RANDOMIZE USR 25000`
#
# After the first run, the IP is cached in .spectrum-ip so you can just `./push.sh`.

set -euo pipefail

HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
IP_FILE="$HERE/.spectrum-ip"

SPECTRUM_IP="${1:-${SPECTRUM_IP:-}}"
if [[ -z "$SPECTRUM_IP" && -f "$IP_FILE" ]]; then
    SPECTRUM_IP="$(cat "$IP_FILE")"
fi
if [[ -z "$SPECTRUM_IP" ]]; then
    echo "usage: $(basename "$0") <spectrum-ip>   (or: SPECTRUM_IP=… $(basename "$0"))" >&2
    exit 1
fi
echo "$SPECTRUM_IP" > "$IP_FILE"

ETHUP="${ETHUP:-$HERE/../spectranet/devtools/ethup}"
if [[ ! -x "$ETHUP" ]]; then
    if command -v ethup >/dev/null 2>&1; then
        ETHUP="$(command -v ethup)"
    else
        echo "ethup not found. Build it with: (cd $(dirname "$ETHUP") && make)" >&2
        exit 1
    fi
fi

BUILD_ARGS=()
if [[ -n "${CHANNELS_HOST:-}" ]]; then
    BUILD_ARGS+=( --build-arg "CHANNELS_HOST=$CHANNELS_HOST" )
    echo ">> Building client (host=$CHANNELS_HOST)…"
else
    echo ">> Building client (host from Dockerfile default)…"
fi
docker build --target client-builder "${BUILD_ARGS[@]}" -t channels-client-test "$HERE" >/dev/null
echo ">> Extracting bin/channels__.bin…"
OUT="$(mktemp --suffix=.bin)"
trap 'rm -f "$OUT"' EXIT
docker run --rm channels-client-test cat /channels/client/bin/channels__.bin > "$OUT"

SIZE="$(wc -c < "$OUT")"
printf '>> %d bytes — load address $61A8 (25000)\n' "$SIZE"

printf '>> On Spectrum: CLEAR 24999, then NMI → "Load arbitrary data..."\n'
printf '   Press Enter here when ready: '
read -r _
"$ETHUP" "$SPECTRUM_IP" "$OUT" 25000
echo ">> Uploaded. On Spectrum: exit NMI, then: RANDOMIZE USR 25000"
