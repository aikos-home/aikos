#!/usr/bin/env python3
"""aikos rollout agent: runs every minute on each node (systemd timer). Standard library only.

1. Which image does `main` point to now? (registry, no pull)
2. New, not marked bad? Check its signature: only images signed by the aikos image workflow on `main` run here.
3. Take the cluster-wide rollout lock (a row in rqlite). Only one node changes at a time.
4. The other nodes must be healthy, so the service never drops below two nodes because of a rollout.
5. Start the new image, wait until /api/v1/health answers with the commit the image was built from.
6. If it does not: back to the previous image, mark the new one bad, release the lock.

Nothing comes in from GitHub; the node fetches. State: /var/lib/aikos/deployer/state.json.
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

LOG = logging.getLogger("aikos-deployer")

IMAGE = os.environ.get("AIKOS_IMAGE", "ghcr.io/aikos-home/aikos-app")
TAG = os.environ.get("AIKOS_IMAGE_TAG", "main")
SIGNER = os.environ.get("AIKOS_SIGNER",
                        "https://github.com/aikos-home/aikos/.github/workflows/app-image.yml@refs/heads/main")
ISSUER = "https://token.actions.githubusercontent.com"
STATE = Path(os.environ.get("AIKOS_DEPLOYER_STATE", "/var/lib/aikos/deployer/state.json"))
IMAGE_ENV = Path("/etc/aikos/app-image.env")
ROLLOUT_FLAG = Path("/run/aikos/rollout")
COMPOSE = ["docker", "compose", "--project-name", "aikos", "--env-file", "/etc/aikos/cluster.env",
           "--env-file", str(IMAGE_ENV), "-f", "/opt/aikos/compose.yaml"]
LOCK_TTL_S = 600
HEALTH_WAIT_S = 120
HANDOVER_WAIT_S = 15
REVISION_LABEL = "org.opencontainers.image.revision"


@dataclass
class State:
    current: str = ""
    previous: str = ""
    bad: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path = STATE) -> "State":
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            return cls(d.get("current", ""), d.get("previous", ""), list(d.get("bad", [])))
        except (OSError, ValueError):
            return cls()

    def save(self, path: Path = STATE) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"current": self.current, "previous": self.previous, "bad": self.bad[-20:]}),
                       encoding="utf-8")
        tmp.replace(path)


def decide(state: State, target: str, healthy: bool) -> str:
    """What to do with the digest `main` points to: 'nothing', 'skip-bad' or 'deploy'."""
    if not target:
        return "nothing"
    if target in state.bad:
        return "skip-bad"
    if target == state.current and healthy:
        return "nothing"
    return "deploy"


# registry and signature
def resolve_digest(image: str = IMAGE, tag: str = TAG) -> str:
    out = run(["docker", "buildx", "imagetools", "inspect", f"{image}:{tag}", "--format", "{{json .Manifest}}"])
    return json.loads(out).get("digest", "")


def signature(ref: str) -> str:
    """'ok', 'missing' (not signed yet: wait, never run it) or 'bad' (signed by someone else or broken: never)."""
    try:
        run(["cosign", "verify", "--certificate-identity", SIGNER, "--certificate-oidc-issuer", ISSUER, ref])
        return "ok"
    except subprocess.CalledProcessError as e:
        err = (e.stderr or "")[-300:]
        if "no signatures found" in err:
            LOG.info("%s is not signed (yet); waiting", ref.rsplit("@", 1)[-1][:19])
            return "missing"
        LOG.error("signature check failed for %s: %s", ref, err)
        return "bad"


# cluster lock in rqlite
class Lock:
    """`INSERT … ON CONFLICT … WHERE`: taken if free, expired, or already ours; one SQL statement, so atomic."""

    def __init__(self, node: str, nodes: list[str], user: str, password: str, ca_file: str) -> None:
        self.node, self.nodes = node, nodes
        self.auth = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
        self.ctx = ssl.create_default_context(cafile=ca_file)

    def _execute(self, statements: list[list]) -> list[dict]:
        last = None
        for n in self.nodes:
            req = urllib.request.Request(f"https://{n}/db/execute?transaction", data=json.dumps(statements).encode(),
                                         headers={"Content-Type": "application/json", "Authorization": self.auth})
            try:
                with urllib.request.urlopen(req, timeout=5, context=self.ctx) as r:
                    results = json.load(r)["results"]
            except (OSError, urllib.error.URLError) as e:
                last = e
                continue
            for res in results:
                if "error" in res:
                    raise RuntimeError(res["error"])
            return results
        raise RuntimeError(f"no database node reachable: {last}")

    def acquire(self) -> bool:
        now = int(time.time())
        res = self._execute([
            ["CREATE TABLE IF NOT EXISTS deploy_lock(name TEXT PRIMARY KEY, holder TEXT NOT NULL, until INTEGER NOT NULL)"],
            ["INSERT INTO deploy_lock(name, holder, until) VALUES ('rollout', ?, ?) ON CONFLICT(name) DO UPDATE SET"
             " holder = excluded.holder, until = excluded.until WHERE deploy_lock.until < ? OR deploy_lock.holder = ?",
             self.node, now + LOCK_TTL_S, now, self.node],
        ])
        return int(res[1].get("rows_affected", 0)) == 1

    def release(self) -> None:
        self._execute([["DELETE FROM deploy_lock WHERE name = 'rollout' AND holder = ?", self.node]])


# health
def health(url: str, timeout: float = 3.0) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            body = json.load(r)
            return body if body.get("ok") else None
    except (OSError, ValueError, urllib.error.URLError):
        return None


def wait_healthy(url: str, commit: str, seconds: int = HEALTH_WAIT_S) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        h = health(url)
        if h and (not commit or h.get("commit") == commit):
            return True
        time.sleep(2)
    return False


def holds_address(vip: str) -> bool:
    return bool(vip) and f" {vip}/" in run(["ip", "-4", "-o", "addr"])


def hand_over_address(vip: str, seconds: int = HANDOVER_WAIT_S) -> None:
    """Planned rollout without a gap: with the rollout flag set, keepalived's health check fails here and a peer takes
    the virtual address (about 2 s). Only then is the app restarted. Without a healthy peer the flag would never move
    it, but then the rollout does not start at all (peers are checked first)."""
    end = time.monotonic() + seconds
    while holds_address(vip) and time.monotonic() < end:
        time.sleep(0.5)
    if holds_address(vip):
        LOG.warning("still holding %s after %d s; restarting anyway", vip, seconds)


# docker
def run(cmd: list[str]) -> str:
    return subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=600).stdout


def start(ref: str) -> None:
    IMAGE_ENV.write_text(f"APP_IMAGE={ref}\n", encoding="utf-8")
    run(COMPOSE + ["pull", "app"])
    run(COMPOSE + ["up", "-d", "--no-deps", "app"])


def revision(ref: str) -> str:
    return run(["docker", "image", "inspect", "--format", "{{ index .Config.Labels \"%s\" }}" % REVISION_LABEL,
                ref]).strip()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--node", default=os.environ.get("NODE_ID", ""))
    p.add_argument("--peers", default=os.environ.get("PEER_IPS", ""), help="comma-separated peer addresses")
    p.add_argument("--db-nodes", default=os.environ.get("DB_NODES", ""))
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    secrets = dict(line.split("=", 1) for line in
                   Path("/etc/aikos/secrets/deployer.env").read_text(encoding="utf-8").split() if "=" in line)

    state = State.load()
    local = "http://127.0.0.1:8780/api/v1/health"
    try:
        target = resolve_digest()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError) as e:
        LOG.warning("cannot read %s:%s from the registry (%s); the running version stays", IMAGE, TAG,
                    (getattr(e, "stderr", "") or str(e)).strip()[-200:])
        return 0
    action = decide(state, target, health(local) is not None)
    if action != "deploy":
        if action == "skip-bad":
            LOG.info("main points to %s, marked bad; waiting for a newer build", target[:19])
        return 0
    ref = f"{IMAGE}@{target}"
    verdict = signature(ref)
    if verdict == "missing":
        return 0
    if verdict == "bad":
        state.bad.append(target)
        state.save()
        return 1

    lock = Lock(args.node, [n for n in args.db_nodes.split(",") if n], secrets["DB_USER"], secrets["DB_PASSWORD"],
                "/etc/aikos/certs/ca.crt")
    if not lock.acquire():
        LOG.info("another node is rolling out; next minute")
        return 0
    try:
        peers = [ip for ip in args.peers.split(",") if ip]
        sick = [ip for ip in peers if health(f"http://{ip}/api/v1/health") is None]
        if state.current and sick:
            LOG.warning("peers not healthy (%s); not taking this node down now", ",".join(sick))
            return 0
        LOG.info("rolling out %s", target[:19])
        # From here this node is out: keepalived hands the address on, the heartbeat skips instead of reporting down.
        ROLLOUT_FLAG.parent.mkdir(parents=True, exist_ok=True)
        ROLLOUT_FLAG.write_text(target, encoding="utf-8")
        hand_over_address(os.environ.get("VIP", ""))
        start(ref)
        commit = revision(ref)
        if wait_healthy(local, commit):
            state.previous, state.current = state.current, target
            state.save()
            LOG.info("now running %s (commit %s)", target[:19], commit[:12])
            return 0
        LOG.error("%s did not become healthy; rolling back", target[:19])
        state.bad.append(target)
        state.save()
        if state.current:
            start(f"{IMAGE}@{state.current}")
            wait_healthy(local, "")
        return 1
    finally:
        ROLLOUT_FLAG.unlink(missing_ok=True)
        try:
            lock.release()
        except RuntimeError as e:
            LOG.warning("lock release: %s (expires by itself)", e)


if __name__ == "__main__":
    sys.exit(main())
