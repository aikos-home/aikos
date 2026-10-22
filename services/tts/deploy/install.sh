#!/bin/sh
# Install or update aikos TTS on a Mac as the LaunchAgent home.aikos.tts (user level, no sudo).
#
#   sh install.sh [--build-only] RELEASE_DIR
#
# RELEASE_DIR is a copy of services/tts (deploy.sh puts each tag into ~/aikos/releases/tts/<tag>). Its venv lives in the
# release, RELEASE_DIR/.venv-<engine>, built once (from this platform's lock file in locks/ when there is one).
# --build-only only builds it (extras <engine>,test) and prints its python as the last line; nothing is started.
#
# Everything that must move to another machine is one folder, AIKOS_TTS_STATE_DIR (default ~/.aikos/tts): voices/ (0700),
# token (0600, the app's), heartbeat-url (0600, the monitor's), tts.env (client lists, the Whisper that checks, the
# engine). The first run COPIES an older install's state (~/aikos/services/tts) there; the old copy stays
# for the way back to an older version. The models are fetched once at pinned commits; the service then starts without
# the internet (HF_HUB_OFFLINE=1). Cache: ~/Library/Caches/aikos/tts. Log: ~/Library/Logs/aikos/tts.log.
set -eu
BUILD_ONLY=0
if [ "${1:-}" = "--build-only" ]; then BUILD_ONLY=1; shift; fi
REL=$(cd "${1:?release dir}" && pwd)
STATE=${AIKOS_TTS_STATE_DIR:-$HOME/.aikos/tts}
OLD="$HOME/aikos/services/tts"
UV=${UV:-$HOME/.local/bin/uv}
LABEL=home.aikos.tts
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOGDIR="$HOME/Library/Logs/aikos"

ENVFILE="$STATE/tts.env"
[ -f "$ENVFILE" ] || ENVFILE="$OLD/tts.env"
AIKOS_TTS_ENGINE=; AIKOS_TTS_WYOMING_CLIENTS=; AIKOS_TTS_HTTP_CLIENTS=; AIKOS_TTS_WHISPER_URL=
if [ -f "$ENVFILE" ]; then . "$ENVFILE"; fi
ENGINE=${AIKOS_TTS_ENGINE:-auto}
if [ "$ENGINE" = auto ]; then
  if [ "$(uname -s)-$(uname -m)" = Darwin-arm64 ]; then ENGINE=chatterbox-mlx; else ENGINE=chatterbox; fi
fi
case "$ENGINE" in
  chatterbox-mlx) EXTRA=mlx ;;
  chatterbox) EXTRA=chatterbox ;;
  *) echo "unknown engine $ENGINE" >&2; exit 2 ;;
esac

# the venv, inside the release
VENV="$REL/.venv-$ENGINE"
PLATFORM="$(uname -s | tr '[:upper:]' '[:lower:]')-$(uname -m)"
LOCK="$REL/locks/$ENGINE-$PLATFORM.txt"
if [ ! -x "$VENV/bin/python" ]; then
  "$UV" venv -q --python 3.11 "$VENV" >&2
  if [ -f "$LOCK" ]; then "$UV" pip install -q --python "$VENV/bin/python" -r "$LOCK" >&2; fi
  "$UV" pip install -q --python "$VENV/bin/python" "$REL[$EXTRA,test]" >&2
fi
if [ "$BUILD_ONLY" = 1 ]; then
  echo "$VENV/bin/python"
  exit 0
fi

# the state: one folder; an older install's is copied, never moved
mkdir -p "$STATE" && chmod 700 "$STATE"
if [ ! -d "$STATE/voices" ] && [ -d "$OLD/voices" ]; then cp -Rp "$OLD/voices" "$STATE/voices"; fi
mkdir -p "$STATE/voices" && chmod 700 "$STATE/voices"
for f in token tts.env; do
  if [ ! -f "$STATE/$f" ] && [ -f "$OLD/$f" ]; then cp -p "$OLD/$f" "$STATE/$f"; fi
done
CACHE="$HOME/Library/Caches/aikos/tts"
if [ ! -d "$CACHE" ] && [ -d "$OLD/cache" ]; then mkdir -p "$(dirname "$CACHE")" && cp -Rp "$OLD/cache" "$CACHE"; fi
if [ ! -f "$STATE/token" ]; then
  (umask 077; "$VENV/bin/python" -c "import secrets; print(secrets.token_urlsafe(32))" > "$STATE/token")
fi
if [ ! -f "$STATE/tts.env" ]; then
  cat > "$STATE/tts.env" <<EOF
AIKOS_TTS_ENGINE=auto
AIKOS_TTS_WYOMING_CLIENTS=
AIKOS_TTS_HTTP_CLIENTS=
AIKOS_TTS_WHISPER_URL=
EOF
  echo "edit $STATE/tts.env (client lists, the Whisper that checks), then run this again" >&2
fi
. "$STATE/tts.env"

# the models, pinned, fetched once (online); afterwards the service starts offline
"$VENV/bin/python" -m aikos_tts fetch --engine "$ENGINE" >&2

mkdir -p "$LOGDIR"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>$VENV/bin/python</string><string>-m</string><string>aikos_tts</string>
    <string>serve</string><string>--engine</string><string>$ENGINE</string>
  </array>
  <key>EnvironmentVariables</key><dict>
    <key>AIKOS_TTS_STATE_DIR</key><string>$STATE</string>
    <key>AIKOS_TTS_WYOMING_CLIENTS</key><string>${AIKOS_TTS_WYOMING_CLIENTS:-}</string>
    <key>AIKOS_TTS_HTTP_CLIENTS</key><string>${AIKOS_TTS_HTTP_CLIENTS:-}</string>
    <key>AIKOS_TTS_WHISPER_URL</key><string>${AIKOS_TTS_WHISPER_URL:-}</string>
    <key>HF_HUB_OFFLINE</key><string>1</string>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/bin:/bin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$LOGDIR/tts.log</string>
  <key>StandardErrorPath</key><string>$LOGDIR/tts.log</string>
</dict></plist>
EOF
uid=$(id -u)
launchctl bootout "gui/$uid/$LABEL" 2>/dev/null || true
for i in 1 2 3 4 5; do   # right after bootout launchd may still be stopping the old one
  launchctl bootstrap "gui/$uid" "$PLIST" 2>/dev/null && break
  sleep 2
done
for i in $(seq 90); do
  if curl -fsS http://127.0.0.1:10201/v1/health >/dev/null 2>&1; then curl -fsS http://127.0.0.1:10201/v1/health; echo; exit 0; fi
  sleep 2
done
echo "aikos TTS did not come up; see $LOGDIR/tts.log" >&2
exit 1
