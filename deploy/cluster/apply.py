#!/usr/bin/env python3
"""Brings the three aikos nodes to the state described in the house inventory. Idempotent: run it again any time.

    python deploy/cluster/apply.py --inventory <private repo>/cluster.toml [--check] [--rotate-certs]

Runs on an admin machine with SSH access to the nodes (user with sudo). Never prints a secret. Shared secrets are
generated once and live only on the nodes (/etc/aikos/secrets/cluster.json, root, 0400); later runs read them back
from a node over SSH, so adding or rebuilding a node gets the same ones.

What it does on every node: packages (keepalived, curl), cosign (pinned, checksum checked), folders, files with owner
and mode, systemd timers, then the database and Caddy; the app itself is started by the rollout agent (it only runs
signed images). Image updates never need this tool: every merge to main is rolled out by the nodes themselves.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pki  # noqa: E402
from render import APP_UID, RQLITE_UID, Inventory, Node, new_cluster_secrets, node_files  # noqa: E402

COSIGN_VERSION = "v2.6.5"
COSIGN_SHA256 = "c3b4f5410e608af03a5eb0aaac84a4313d8da131248e08ff1759ac70c79d1644"
DIRS = [  # path, mode, owner
    ("/opt/aikos", "0755", "root:root"), ("/usr/local/lib/aikos", "0755", "root:root"),
    ("/etc/aikos", "0755", "root:root"), ("/etc/aikos/certs", "0755", "root:root"),
    ("/etc/aikos/caddy", "0755", "root:root"),
    ("/etc/aikos/secrets", "0750", "root:root"), ("/etc/aikos/secrets/app", "0700", f"{APP_UID}:{APP_UID}"),
    ("/var/lib/aikos/rqlite", "0700", f"{RQLITE_UID}:{RQLITE_UID}"),
    ("/var/lib/aikos/app", "0700", f"{APP_UID}:{APP_UID}"),
    ("/var/lib/aikos/caddy", "0700", "root:root"), ("/var/lib/aikos/deployer", "0700", "root:root"),
    ("/var/backups/aikos", "0750", "root:aikos"),
]


class Ssh:
    def __init__(self, user: str, key: str) -> None:
        self.base = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=accept-new"]
        if key:
            self.base += ["-i", str(Path(key).expanduser())]
        self.user = user

    def run(self, ip: str, script: str, stdin: bytes | None = None, check: bool = True) -> str:
        p = subprocess.run(self.base + [f"{self.user}@{ip}", script], input=stdin, capture_output=True, timeout=900)
        if check and p.returncode != 0:
            raise RuntimeError(f"{ip}: {script.splitlines()[0][:80]} → exit {p.returncode}: "
                               f"{p.stderr.decode(errors='replace')[-400:]}")
        return p.stdout.decode(errors="replace")

    def put(self, ip: str, path: str, content: str, mode: str, owner: str) -> None:
        q = shlex.quote(path)
        self.run(ip, f"sudo sh -c 'umask 077 && cat > {q}.tmp && chown {owner} {q}.tmp && chmod {mode} {q}.tmp"
                     f" && mv {q}.tmp {q}'", stdin=content.encode())

    def read_secret(self, ip: str, path: str) -> str | None:
        out = self.run(ip, f"sudo cat {shlex.quote(path)} 2>/dev/null || true")
        return out or None


def load_secrets(ssh: Ssh, inv: Inventory) -> dict:
    for n in inv.nodes:
        raw = ssh.read_secret(n.ip, "/etc/aikos/secrets/cluster.json")
        if raw:
            print(f"  shared secrets: found on {n.name}")
            return json.loads(raw)
    print("  shared secrets: none yet, generating (only on the nodes, never printed)")
    return new_cluster_secrets(*pki.new_ca())


def node_cert_for(ssh: Ssh, node: Node, sec: dict, rotate: bool) -> tuple[str, str]:
    if not rotate:
        crt = ssh.read_secret(node.ip, "/etc/aikos/certs/node.crt")
        key = ssh.read_secret(node.ip, "/etc/aikos/certs/node.key")
        ca = ssh.read_secret(node.ip, "/etc/aikos/certs/ca.crt")
        if crt and key and ca == sec["ca_cert"]:
            return crt, key
    return pki.node_cert(sec["ca_cert"], sec["ca_key"], node.name, node.ip)


def prepare_host(ssh: Ssh, node: Node) -> str:
    """Packages, cosign, folders. Returns the network interface of the house network."""
    ssh.run(node.ip, "command -v keepalived >/dev/null && command -v curl >/dev/null || "
                     "(sudo DEBIAN_FRONTEND=noninteractive apt-get -qq update && "
                     "sudo DEBIAN_FRONTEND=noninteractive apt-get -qq install -y keepalived curl)")
    ssh.run(node.ip, f"""set -e
if ! cosign version 2>/dev/null | grep -q 'GitVersion:.*{COSIGN_VERSION}'; then
  t=$(mktemp)
  curl -fsSL -o "$t" https://github.com/sigstore/cosign/releases/download/{COSIGN_VERSION}/cosign-linux-amd64
  echo "{COSIGN_SHA256}  $t" | sha256sum -c --quiet
  sudo install -m 0755 "$t" /usr/local/bin/cosign
  rm -f "$t"
fi""")
    for path, mode, owner in DIRS:
        ssh.run(node.ip, f"sudo install -d -m {mode} -o {owner.split(':')[0]} -g {owner.split(':')[1]} {path}")
    iface = ssh.run(node.ip, "ip -o -4 route get 1.1.1.1 | awk '{for(i=1;i<=NF;i++) if($i==\"dev\") print $(i+1)}'")
    return iface.strip()


def registry_read_token(inv: Inventory) -> str:
    """For a private image: a read-only registry token from a file on the admin machine (none = public image)."""
    if not inv.registry_token_file:
        return ""
    path = Path(inv.registry_token_file).expanduser()
    if not path.is_file():
        raise SystemExit(f"registry token file missing: {path}")
    return path.read_text(encoding="utf-8").strip()


def compose(ssh: Ssh, ip: str, *args: str) -> str:
    image_env = "/etc/aikos/app-image.env"
    return ssh.run(ip, f"sudo touch {image_env} && sudo docker compose --project-name aikos "
                       f"--env-file /etc/aikos/cluster.env --env-file {image_env} -f /opt/aikos/compose.yaml "
                       + " ".join(shlex.quote(a) for a in args))


def wait_database(ssh: Ssh, inv: Inventory, sec: dict, seconds: int = 120) -> None:
    """Every node answers a query as the app user, i.e. the cluster has a leader and TLS + auth work."""
    pw = sec["passwords"]["app"]
    end = time.monotonic() + seconds
    pending = list(inv.nodes)
    while pending and time.monotonic() < end:
        n = pending[0]
        # credentials go in on stdin as a curl config, so they never appear in a process list
        out = ssh.run(n.ip, f"curl -fsS --max-time 4 --cacert /etc/aikos/certs/ca.crt -K - "
                            f"-H 'Content-Type: application/json' -d '[[\"SELECT 1 AS ok\"]]' "
                            f"'https://{n.ip}:4001/db/query?associative' || true",
                      stdin=f'user = "app:{pw}"\n'.encode())
        if '"ok":1' in out.replace(" ", ""):
            print(f"  database answers on {n.name}")
            pending.pop(0)
        else:
            time.sleep(3)
    if pending:
        raise RuntimeError("database not ready on " + ", ".join(n.name for n in pending))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--inventory", required=True)
    ap.add_argument("--check", action="store_true", help="only check that every node is reachable with sudo")
    ap.add_argument("--rotate-certs", action="store_true", help="new node certificates from the existing CA")
    ap.add_argument("--rotate-ca", action="store_true",
                    help="new cluster CA and node certificates (passwords stay); restarts the database on all nodes")
    args = ap.parse_args(argv)
    inv = Inventory.from_dict(tomllib.loads(Path(args.inventory).read_text(encoding="utf-8")))
    ssh = Ssh(inv.ssh_user, inv.ssh_key)

    for n in inv.nodes:
        print(f"{n.name} {n.ip}: {ssh.run(n.ip, 'hostname && sudo -n true && docker compose version --short').split()}")
    if args.check:
        return 0
    sec = load_secrets(ssh, inv)
    if args.rotate_ca:
        sec["ca_cert"], sec["ca_key"] = pki.new_ca()
        args.rotate_certs = True
    ha_token = Path(inv.ha_token_file).expanduser().read_text(encoding="utf-8").strip()
    tts_token = Path(inv.tts_token_file).expanduser().read_text(encoding="utf-8").strip() if inv.tts_token_file else ""
    registry_token = registry_read_token(inv)
    for n in inv.nodes:
        print(f"{n.name}: host")
        iface = prepare_host(ssh, n)
        crt, key = node_cert_for(ssh, n, sec, args.rotate_certs)
        for f in node_files(inv, n, sec, crt, key, ha_token, iface, tts_token):
            ssh.put(n.ip, f.path, f.content, f.mode, f.owner)
        if registry_token:
            # root's Docker credentials (0600) serve docker pull, buildx imagetools and cosign alike; token on stdin only
            ssh.run(n.ip, f"sudo docker login ghcr.io -u {shlex.quote(inv.registry_user)} --password-stdin >/dev/null",
                    stdin=registry_token.encode())
        ssh.run(n.ip, "sudo systemctl daemon-reload && "
                      "sudo systemctl enable --now aikos-db-backup.timer aikos-heartbeat.timer >/dev/null")
    print("database and Caddy on all nodes")
    for n in inv.nodes:
        ssh.run(n.ip, "sudo rm -f /etc/aikos/Caddyfile")  # old single-file location (before the folder mount)
        compose(ssh, n.ip, "up", "-d", "--remove-orphans", "rqlite", "caddy")
        if args.rotate_certs:  # rqlite and the app read certificates at start; the three restart within seconds
            compose(ssh, n.ip, "restart", "rqlite")
            ssh.run(n.ip, "sudo docker restart aikos-app-1 >/dev/null 2>&1 || true")
        # Compose does not notice a changed Caddyfile; a graceful reload picks it up without dropping connections.
        compose(ssh, n.ip, "exec", "-T", "caddy", "caddy", "reload", "--config", "/etc/caddy/Caddyfile",
                "--adapter", "caddyfile")
    wait_database(ssh, inv, sec)
    for n in inv.nodes:
        ssh.run(n.ip, "sudo systemctl enable --now aikos-deployer.timer >/dev/null && sudo systemctl restart keepalived"
                      " && sudo systemctl enable keepalived >/dev/null")
    print("done: the rollout agents start the signed app image within a few minutes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
