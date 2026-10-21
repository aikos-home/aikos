"""Turns the house inventory plus the cluster secrets into the files of one node. No I/O here, so it is testable."""

from __future__ import annotations

import json
import secrets
import string
from dataclasses import dataclass, field
from pathlib import Path
from string import Template

HERE = Path(__file__).resolve().parent
APP_UID, RQLITE_UID = 10001, 1000


@dataclass(frozen=True)
class Node:
    name: str
    ip: str
    priority: int


@dataclass(frozen=True)
class Inventory:
    domain: str
    vip: str
    prefix: int
    vrid: int
    trusted_proxies: str
    ha_url: str
    ha_token_file: str
    nodes: list[Node]
    app: dict[str, str] = field(default_factory=dict)
    ssh_user: str = "aikos"
    ssh_key: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Inventory":
        c, ha, ssh = d["cluster"], d["ha"], d.get("ssh", {})
        nodes = [Node(n["name"], n["ip"], int(n.get("priority", 100))) for n in d["nodes"]]
        if len(nodes) != 3:
            raise ValueError("the cluster has exactly three nodes")
        return cls(c["domain"], c["vip"], int(c.get("prefix", 24)), int(c.get("vrid", 229)),
                   c.get("trusted_proxies", ""), ha["url"], ha.get("token_file", ""), nodes,
                   {k: str(v) for k, v in d.get("app", {}).items()}, ssh.get("user", "aikos"), ssh.get("key", ""))


def new_cluster_secrets(ca_cert: str, ca_key: str) -> dict:
    """Shared by all three nodes. VRRP's simple password is at most 8 characters."""
    alnum = string.ascii_letters + string.digits
    return {"version": 1, "ca_cert": ca_cert, "ca_key": ca_key,
            "passwords": {u: secrets.token_urlsafe(24) for u in ("cluster", "app", "deployer", "backup")},
            "vrrp": "".join(secrets.choice(alnum) for _ in range(8))}


def _env(pairs: dict[str, str]) -> str:
    for k, v in pairs.items():
        if "\n" in v or " " in v:
            raise ValueError(f"{k}: no spaces or line breaks in environment values")
    return "".join(f"{k}={v}\n" for k, v in pairs.items())


def cluster_env(inv: Inventory, node: Node) -> str:
    peers = [n for n in inv.nodes if n != node]
    return _env({
        "NODE_ID": node.name, "NODE_IP": node.ip,
        "PEER_IPS": ",".join(p.ip for p in peers),
        "PEERS_RAFT": ",".join(f"{n.ip}:4002" for n in inv.nodes),
        "DB_NODES": ",".join(f"{n.ip}:4001" for n in [node, *peers]),
        "DOMAIN": inv.domain, "VIP": inv.vip, "TRUSTED_PROXIES": inv.trusted_proxies or "127.0.0.1",
    })


def app_env(inv: Inventory, node: Node) -> str:
    peers = [n for n in inv.nodes if n != node]
    base = {
        "AIKOS_APP_PUBLIC_URL": f"https://{inv.domain}",
        "AIKOS_APP_LISTEN": "127.0.0.1", "AIKOS_APP_PORT": "8780", "AIKOS_APP_TRUST_PROXY": "1",
        "AIKOS_APP_DATA_DIR": "/data",
        "AIKOS_APP_DB": "rqlites://" + ",".join(f"{n.ip}:4001" for n in [node, *peers]),
        "AIKOS_APP_DB_USER": "app", "AIKOS_APP_DB_PASSWORD_FILE": "/secrets/db-password",
        "AIKOS_APP_DB_CA_FILE": "/certs/ca.crt",
        "AIKOS_APP_HA_URL": inv.ha_url, "AIKOS_APP_HA_TOKEN_FILE": "/secrets/ha-token",
    }
    base.update({f"AIKOS_APP_{k.upper()}": v for k, v in inv.app.items()})
    return _env(base)


def rqlite_auth(sec: dict) -> str:
    p = sec["passwords"]
    return json.dumps([
        {"username": "cluster", "password": p["cluster"], "perms": ["join", "join-read-only", "remove"]},
        {"username": "app", "password": p["app"], "perms": ["execute", "query"]},
        {"username": "deployer", "password": p["deployer"], "perms": ["execute", "query"]},
        {"username": "backup", "password": p["backup"], "perms": ["backup"]},
    ], indent=1)


def keepalived_conf(inv: Inventory, node: Node, sec: dict, iface: str) -> str:
    peers = [n for n in inv.nodes if n != node]
    return Template((HERE / "keepalived.conf.tmpl").read_text(encoding="utf-8")).substitute(
        NODE_ID=node.name, IFACE=iface, VRID=inv.vrid, PRIORITY=node.priority, NODE_IP=node.ip,
        PEER_LINES="\n".join(f"        {p.ip}" for p in peers), VRRP_PASS=sec["vrrp"], VIP=inv.vip, PREFIX=inv.prefix)


@dataclass(frozen=True)
class File:
    path: str
    content: str
    mode: str = "0644"
    owner: str = "root:root"


def node_files(inv: Inventory, node: Node, sec: dict, node_cert: str, node_key: str, ha_token: str,
               iface: str) -> list[File]:
    """Every file on a node, with owner and mode. Secrets only readable by the one process that needs them."""
    p = sec["passwords"]
    kit = lambda name: (HERE / name).read_text(encoding="utf-8")  # noqa: E731
    return [
        File("/opt/aikos/compose.yaml", kit("compose.yaml")),
        File("/etc/aikos/Caddyfile", kit("Caddyfile")),
        File("/etc/aikos/cluster.env", cluster_env(inv, node)),
        File("/etc/aikos/app.env", app_env(inv, node)),
        File("/etc/aikos/certs/ca.crt", sec["ca_cert"]),
        File("/etc/aikos/certs/node.crt", node_cert),
        File("/etc/aikos/certs/node.key", node_key, "0400", f"{RQLITE_UID}:{RQLITE_UID}"),
        File("/etc/aikos/secrets/cluster.json", json.dumps(sec), "0400"),
        File("/etc/aikos/secrets/rqlite-auth.json", rqlite_auth(sec), "0400", f"{RQLITE_UID}:{RQLITE_UID}"),
        File("/etc/aikos/secrets/app/db-password", p["app"], "0400", f"{APP_UID}:{APP_UID}"),
        File("/etc/aikos/secrets/app/ha-token", ha_token, "0400", f"{APP_UID}:{APP_UID}"),
        File("/etc/aikos/secrets/deployer.env", f"DB_USER=deployer\nDB_PASSWORD={p['deployer']}\n", "0400"),
        File("/etc/aikos/secrets/backup.env", f"DB_USER=backup\nDB_PASSWORD={p['backup']}\n", "0400"),
        File("/etc/keepalived/keepalived.conf", keepalived_conf(inv, node, sec, iface), "0600"),
        File("/usr/local/lib/aikos/check-health", kit("check-health"), "0755"),
        File("/usr/local/lib/aikos/aikos_deployer.py", kit("aikos_deployer.py"), "0755"),
        File("/usr/local/lib/aikos/aikos_db_backup.py", kit("aikos_db_backup.py"), "0755"),
        File("/usr/local/lib/aikos/aikos_heartbeat.py", kit("aikos_heartbeat.py"), "0755"),
        *[File(f"/etc/systemd/system/{u}", kit(f"systemd/{u}"))
          for u in ("aikos-deployer.service", "aikos-deployer.timer", "aikos-db-backup.service",
                    "aikos-db-backup.timer", "aikos-heartbeat.service", "aikos-heartbeat.timer")],
    ]
