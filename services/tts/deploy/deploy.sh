#!/bin/bash
# aikos TTS: roll out one tagged version on this Mac, check it, and roll back by itself if the check fails.
#
#   git -C ~/aikos/repo fetch --tags
#   git -C ~/aikos/repo show tts-v0.6.0:services/tts/deploy/deploy.sh > /tmp/tts-deploy.sh
#   bash /tmp/tts-deploy.sh tts-v0.6.0
#
#   1. export the tag's services/tts into a release folder of its own, ~/aikos/releases/tts/<tag> (git archive from the
#      clone ~/aikos/repo; that clone's working tree, which the transcriber runs from, is never touched)
#   2. the release's installer builds its environment (install.sh --build-only); the unit tests run with it on this Mac;
#      red = nothing is changed
#   3. back up the LaunchAgent to ~/.aikos/backup, then the release's installer writes it and starts the service
#   4. the health must report the tag's version, and the self-test must speak a fixed sentence with the model's built-in
#      voice and pass the Whisper check (a resident's voice is never used for a test)
#   A failure in 3-4 brings back the previous LaunchAgent (and with it the previous release) and exits 1.
#   After a success the newest AIKOS_KEEP releases (default 3) stay, older ones are removed.
#
# Environment: AIKOS_REPO (default ~/aikos/repo), AIKOS_RELEASES (default ~/aikos/releases/tts), AIKOS_TTS_URL (the
# service's HTTP side on this machine, default http://127.0.0.1:10201), AIKOS_HEALTH_WAIT_S (default 180).
# The settings (engine, client lists, heartbeat) are the installer's: ~/.aikos/tts/tts.env.
# Written for macOS /bin/bash 3.2 with set -u: no arrays.
set -eu -o pipefail

tag="${1:?usage: deploy.sh <tag, e.g. tts-v0.6.0>}"
repo="${AIKOS_REPO:-$HOME/aikos/repo}"
releases="${AIKOS_RELEASES:-$HOME/aikos/releases/tts}"
url="${AIKOS_TTS_URL:-http://127.0.0.1:10201}"
wait_s="${AIKOS_HEALTH_WAIT_S:-180}"
keep="${AIKOS_KEEP:-3}"
label=home.aikos.tts
plist="$HOME/Library/LaunchAgents/$label.plist"
logs="$HOME/Library/Logs/aikos"
backup="$HOME/.aikos/backup"
uid=$(id -u)
stamp=$(date +%Y%m%d%H%M%S)
mkdir -p "$logs" "$backup" "$releases"
note() { echo "$(date '+%F %T') tts deploy: $*" | tee -a "$logs/deploy.log"; }

# tts-v0.6.0 -> 0.6.0: the version the health must report
version_of() { case "$1" in tts-v[0-9]*) echo "${1#tts-v}" ;; *) echo "" ;; esac; }
# the "version" field of a health answer on stdin, "" if there is none
health_version() { sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1; }
# true when a JSON answer on stdin says "ok": true
says_ok() { grep -Eq '"ok"[[:space:]]*:[[:space:]]*true'; }
# the newest releases first, by when they were deployed
newest_first() { ls -1t "$1" 2>/dev/null || true; }

want=$(version_of "$tag")
if [ -z "$want" ]; then
  note "$tag is not a voice service tag (tts-vX.Y.Z); nothing changed"
  exit 1
fi

# 1. the release
git -C "$repo" fetch --quiet --tags origin || note "fetch failed, using the tags already here"
if ! git -C "$repo" rev-parse --verify --quiet "$tag^{commit}" >/dev/null; then
  note "no tag $tag in $repo; nothing changed"
  exit 1
fi
rel="$releases/$tag"
if [ ! -d "$rel" ]; then
  tmp="$releases/.$tag.$stamp"
  mkdir -p "$tmp"
  if ! git -C "$repo" archive --format=tar "$tag" services/tts | tar -x -C "$tmp"; then
    rm -rf "$tmp"
    note "could not export $tag; nothing changed"
    exit 1
  fi
  mv "$tmp/services/tts" "$rel"
  rm -rf "$tmp"
fi
touch "$rel"
note "$tag = $(git -C "$repo" rev-parse --short "$tag^{commit}") in $rel"

# 2. environment and unit tests (nothing is running from this release yet)
py=$(sh "$rel/deploy/install.sh" --build-only "$rel" 2>>"$logs/deploy.log" | tail -n 1) || py=""
if [ -z "$py" ] || [ ! -x "$py" ]; then
  note "building the environment failed, nothing changed (details in $logs/deploy.log)"
  exit 1
fi
if ! (cd "$rel" && "$py" -m pytest -q >>"$logs/deploy.log" 2>&1); then
  note "unit tests red, nothing changed (details in $logs/deploy.log)"
  exit 1
fi

rollback() {
  note "ROLLBACK: $*"
  launchctl bootout "gui/$uid/$label" 2>/dev/null || true
  if [ -f "$backup/$label.plist.$stamp" ]; then
    cp "$backup/$label.plist.$stamp" "$plist"
    sleep 1
    launchctl bootstrap "gui/$uid" "$plist" 2>/dev/null || { sleep 2; launchctl bootstrap "gui/$uid" "$plist" || true; }
    back=""
    for _ in $(seq 1 "$wait_s"); do
      back=$(curl -fsS -m 5 "$url/v1/health" 2>/dev/null | health_version) || back=""
      if [ -n "$back" ]; then break; fi
      sleep 1
    done
    note "rolled back: the previous version answers: ${back:-NOTHING}"
  else
    rm -f "$plist"                                       # there was none before: the new one goes
    note "rolled back: there was no voice service before, none is running now"
  fi
  exit 1
}

# 3. LaunchAgent: the release's installer writes it and starts the service
if [ -f "$plist" ]; then cp "$plist" "$backup/$label.plist.$stamp"; fi
sh "$rel/deploy/install.sh" "$rel" >>"$logs/deploy.log" 2>&1 || rollback "the installer failed (details in $logs/deploy.log)"

# 4. the right version answers (the old process may still answer for a moment while it stops), and it speaks
got=""
for _ in $(seq 1 "$wait_s"); do
  got=$(curl -fsS -m 5 "$url/v1/health" 2>/dev/null | health_version) || got=""
  if [ "$got" = "$want" ]; then break; fi
  sleep 1
done
[ "$got" = "$want" ] || rollback "health says version '${got:-nothing}', expected $want"
answer=$(curl -fsS -m 120 -X POST "$url/v1/selftest" 2>>"$logs/deploy.log") || answer=""
echo "$answer" >>"$logs/deploy.log"
echo "$answer" | says_ok || rollback "self-test failed: ${answer:-no answer}"

# old releases
n=0
for r in $(newest_first "$releases"); do
  n=$((n + 1))
  if [ "$n" -gt "$keep" ] && [ "$releases/$r" != "$rel" ]; then rm -rf "${releases:?}/$r"; fi
done
note "OK: $tag live, health $got, self-test passed"
