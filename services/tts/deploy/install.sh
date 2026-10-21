#!/bin/sh
# Install or update aikos TTS on the Mac as the LaunchAgent home.aikos.tts (user level, no sudo).
#
#   sh install.sh SOURCE_DIR
#
# SOURCE_DIR is a copy of services/tts. Everything lives in ~/aikos/services/tts: the venv (.venv-clone), the voices (0700),
# the token for the aikos app (token, 0600, created once) and the settings (tts.env, created once; edit the client lists
# there: Home Assistant machines for Wyoming, the app's nodes for HTTP). Logs: ~/Library/Logs/aikos-tts.log.
set -eu
SRC=${1:?source dir}
HOME_DIR="$HOME/aikos/services/tts"
VENV="$HOME_DIR/.venv-clone"
UV="$HOME/.local/bin/uv"
LABEL=home.aikos.tts
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

mkdir -p "$HOME_DIR/voices" && chmod 700 "$HOME_DIR/voices"
[ -x "$VENV/bin/python" ] || "$UV" venv -q --python 3.11 "$VENV"
"$UV" pip install -q --python "$VENV/bin/python" "$SRC[chatterbox]"

if [ ! -f "$HOME_DIR/token" ]; then
  (umask 077; "$VENV/bin/python" -c "import secrets; print(secrets.token_urlsafe(32))" > "$HOME_DIR/token")
fi
if [ ! -f "$HOME_DIR/tts.env" ]; then
  cat > "$HOME_DIR/tts.env" <<EOF
AIKOS_TTS_WYOMING_CLIENTS=
AIKOS_TTS_HTTP_CLIENTS=
AIKOS_TTS_WHISPER_URL=
EOF
  echo "edit $HOME_DIR/tts.env (client lists), then run this again" >&2
fi
. "$HOME_DIR/tts.env"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>$VENV/bin/python</string><string>-m</string><string>aikos_tts</string>
    <string>--voices</string><string>$HOME_DIR/voices</string>
  </array>
  <key>EnvironmentVariables</key><dict>
    <key>AIKOS_TTS_TOKEN_FILE</key><string>$HOME_DIR/token</string>
    <key>AIKOS_TTS_WYOMING_CLIENTS</key><string>$AIKOS_TTS_WYOMING_CLIENTS</string>
    <key>AIKOS_TTS_HTTP_CLIENTS</key><string>$AIKOS_TTS_HTTP_CLIENTS</string>
    <key>AIKOS_TTS_WHISPER_URL</key><string>${AIKOS_TTS_WHISPER_URL:-}</string>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/bin:/bin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/aikos-tts.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/aikos-tts.log</string>
</dict></plist>
EOF
uid=$(id -u)
launchctl bootout "gui/$uid/$LABEL" 2>/dev/null || true
for i in 1 2 3 4 5; do   # right after bootout launchd may still be stopping the old one
  launchctl bootstrap "gui/$uid" "$PLIST" 2>/dev/null && break
  sleep 2
done
for i in $(seq 90); do
  curl -fsS http://127.0.0.1:10201/v1/health >/dev/null 2>&1 && { curl -fsS http://127.0.0.1:10201/v1/health; echo; exit 0; }
  sleep 2
done
echo "aikos TTS did not come up; see ~/Library/Logs/aikos-tts.log" >&2
exit 1
