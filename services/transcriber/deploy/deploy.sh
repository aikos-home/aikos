#!/bin/bash
# aikos transcriber: roll out one version on this Mac, check it, and roll back by itself if the check fails.
#
#   bash ~/aikos/repo/services/transcriber/deploy/deploy.sh transcriber-v1.0.0
#
#   1. check out the version in ~/aikos/repo (a tag: tags never move; the first run clones the repository)
#   2. unit tests with the agents' Python (AIKOS_PYTHON, else /usr/bin/python3); red = nothing is changed
#   3. back up both LaunchAgents to ~/.aikos/backup and write new ones (deploy/launchd.py)
#   4. restart both; both receivers must listen within 15 s
#   5. one spoken test utterance per side must reach Home Assistant (deploy/smoke.py, *_test entities only)
#   A failure in 3-5 brings back the previous LaunchAgents and checkout and exits 1.
#
# Settings: ~/.aikos/transcriber.env (see transcriber.env.example). Without it, the settings are taken over once from
# the existing transcriber LaunchAgents. Environment: AIKOS_REPO (default ~/aikos/repo), AIKOS_ENV.
# AIKOS_PYTHON in the settings file pins the interpreter (absolute path).
# Written for macOS /bin/bash 3.2 with set -u: no arrays.
set -eu -o pipefail
if [ -z "${AIKOS_DEPLOY_COPY:-}" ]; then                 # the checkout below may replace this file: run from a copy
  copy=$(mktemp /tmp/aikos-deploy.XXXXXX)
  cp "$0" "$copy"
  AIKOS_DEPLOY_COPY="$copy" exec /bin/bash "$copy" "$@"
fi
trap 'rm -f "$AIKOS_DEPLOY_COPY"' EXIT

ref="${1:?usage: deploy.sh <tag or commit>}"
repo="${AIKOS_REPO:-$HOME/aikos/repo}"
envf="${AIKOS_ENV:-$HOME/.aikos/transcriber.env}"
agents="$HOME/Library/LaunchAgents"
logs="$HOME/Library/Logs/aikos"
backup="$HOME/.aikos/backup"
uid=$(id -u)
stamp=$(date +%Y%m%d%H%M%S)
mkdir -p "$logs" "$backup"
note() { echo "$(date '+%F %T') deploy: $*" | tee -a "$logs/deploy.log"; }
# The Python of both agents and of this script: AIKOS_PYTHON from the settings file, a pinned interpreter (absolute path, e.g.
# uv-managed) that no macOS or Command Line Tools update swaps underneath; without it Apple's /usr/bin/python3 as before.
interpreter() { { grep -E '^AIKOS_PYTHON=' "$1" 2>/dev/null || true; } | tail -n 1 | cut -d= -f2- | tr -d '"'; }
py=$(interpreter "$envf")
py="${py:-/usr/bin/python3}"
if [ ! -x "$py" ]; then
  note "AIKOS_PYTHON=$py is not an executable file (it must be an absolute path); nothing changed"
  exit 1
fi
plist() { echo "$agents/home.aikos.transcriber.$1.plist"; }
# lsof exits non-zero on mere warnings (e.g. an unreachable network mount): under pipefail that must not end the script
listening() { { lsof -nP -iUDP:5006 -iUDP:5008 2>/dev/null || true; } | awk 'NR>1' | wc -l | tr -d ' '; }

restart() {   # $1 = room | door
  launchctl bootout "gui/$uid/home.aikos.transcriber.$1" 2>/dev/null || true
  sleep 1
  launchctl bootstrap "gui/$uid" "$(plist "$1")" 2>/dev/null || { sleep 2; launchctl bootstrap "gui/$uid" "$(plist "$1")"; }
}

rollback() {
  note "ROLLBACK: $*"
  for side in room door; do
    if [ -f "$backup/home.aikos.transcriber.$side.plist.$stamp" ]; then
      cp "$backup/home.aikos.transcriber.$side.plist.$stamp" "$(plist "$side")"
    fi
    restart "$side" || note "could not start the previous $side agent"
  done
  if [ -n "$prev" ]; then git -C "$repo" checkout --quiet --detach "$prev"; fi
  sleep 3
  note "rolled back: $(listening)/2 receivers listening"
  exit 1
}

# 1. the version
if [ ! -d "$repo/.git" ]; then
  git clone --quiet https://github.com/aikos-home/aikos.git "$repo"
fi
prev=$(git -C "$repo" rev-parse --verify --quiet HEAD || true)
git -C "$repo" fetch --quiet --tags origin
git -C "$repo" checkout --quiet --detach "$ref"
svc="$repo/services/transcriber"
note "$ref = $(git -C "$repo" rev-parse --short HEAD) (checkout before: ${prev:-none})"

# 2. unit tests
if ! (cd "$svc" && "$py" -m unittest discover -s tests >>"$logs/deploy.log" 2>&1); then
  note "unit tests red, nothing changed (details in $logs/deploy.log)"
  if [ -n "$prev" ]; then git -C "$repo" checkout --quiet --detach "$prev"; fi
  exit 1
fi

# 3. settings and LaunchAgents
if [ ! -f "$envf" ]; then
  if [ -f "$(plist room)" ] && [ -f "$(plist door)" ]; then
    "$py" "$svc/deploy/launchd.py" --env "$envf" --import-from "$(plist room)" "$(plist door)"
    note "settings taken over from the existing LaunchAgents into $envf"
  else
    note "no settings: copy $svc/deploy/transcriber.env.example to $envf and fill it in"
    exit 1
  fi
fi
for side in room door; do
  if [ -f "$(plist "$side")" ]; then cp "$(plist "$side")" "$backup/home.aikos.transcriber.$side.plist.$stamp"; fi
done
"$py" "$svc/deploy/launchd.py" --env "$envf" --checkout "$repo" --agents "$agents" --logs "$logs" --python "$py" >/dev/null \
  || rollback "could not write the LaunchAgents"

# 4. restart
restart room || rollback "the room agent did not start"
restart door || rollback "the door agent did not start"
n=0
for _ in $(seq 1 15); do
  n=$(listening)
  if [ "$n" -ge 2 ]; then break; fi
  sleep 1
done
[ "$n" -ge 2 ] || rollback "only $n/2 receivers listening"

# 5. one utterance per side
"$py" "$svc/deploy/smoke.py" --env "$envf" 2>&1 | tee -a "$logs/deploy.log" || rollback "smoke test failed"
note "OK: $ref live, 2/2 receivers, both sides answered"
