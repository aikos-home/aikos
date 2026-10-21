"""The cluster kit without a cluster: rendered files, the rollout decision, the lock statement, file permissions."""

from __future__ import annotations

import json
import sqlite3
import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import aikos_deployer as dep  # noqa: E402
import pki  # noqa: E402
from render import Inventory, new_cluster_secrets, node_files  # noqa: E402

INV = Inventory.from_dict(tomllib.loads((HERE / "cluster.example.toml").read_text(encoding="utf-8")))
SEC = new_cluster_secrets(*pki.new_ca())


def files_of(i: int) -> dict:
    node = INV.nodes[i]
    crt, key = pki.node_cert(SEC["ca_cert"], SEC["ca_key"], node.name, node.ip)
    return {f.path: f for f in node_files(INV, node, SEC, crt, key, "ha-token-value", "eth0")}


def env(text: str) -> dict:
    return dict(line.split("=", 1) for line in text.splitlines() if line)


def test_every_node_lists_itself_first_and_all_three_for_raft():
    for i, node in enumerate(INV.nodes):
        e = env(files_of(i)["/etc/aikos/cluster.env"].content)
        assert e["NODE_IP"] == node.ip and e["DB_NODES"].split(",")[0] == f"{node.ip}:4001"
        assert len(e["PEERS_RAFT"].split(",")) == 3 and node.ip not in e["PEER_IPS"]


def test_app_env_points_at_https_database_and_the_domain():
    e = env(files_of(0)["/etc/aikos/app.env"].content)
    assert e["AIKOS_APP_DB"].startswith("rqlites://") and e["AIKOS_APP_PUBLIC_URL"] == "https://app.example.org"
    assert e["AIKOS_APP_LISTEN"] == "127.0.0.1" and e["AIKOS_APP_DOOR_MEDIA_DIR"] == "aikos_door"
    assert "ha-token-value" not in files_of(0)["/etc/aikos/app.env"].content


def test_secrets_are_readable_only_by_their_process():
    f = files_of(1)
    for path in ("/etc/aikos/secrets/cluster.json", "/etc/aikos/secrets/deployer.env", "/etc/aikos/secrets/backup.env"):
        assert f[path].mode == "0400" and f[path].owner == "root:root", path
    assert f["/etc/aikos/secrets/app/ha-token"].owner == "10001:10001" and f["/etc/aikos/secrets/app/ha-token"].mode == "0400"
    assert f["/etc/aikos/certs/node.key"].owner == "1000:1000" and f["/etc/aikos/certs/node.key"].mode == "0400"
    assert f["/etc/keepalived/keepalived.conf"].mode == "0600"
    public = [p for p, x in f.items() if x.mode.endswith("4") or x.mode.endswith("5")]
    for p in public:
        for secret in [*SEC["passwords"].values(), SEC["vrrp"], "ha-token-value", SEC["ca_key"]]:
            assert secret not in f[p].content, p


def test_rqlite_users_have_only_their_rights():
    users = {u["username"]: u["perms"] for u in json.loads(files_of(0)["/etc/aikos/secrets/rqlite-auth.json"].content)}
    assert users["app"] == ["execute", "query"] and users["backup"] == ["backup"]
    assert "all" not in sum(users.values(), [])


def test_keepalived_unicast_to_the_two_peers():
    conf = files_of(2)["/etc/keepalived/keepalived.conf"].content
    assert "unicast_src_ip 192.0.2.33" in conf and "192.0.2.31" in conf and "192.0.2.32" in conf
    assert "nopreempt" in conf and "192.0.2.29/24 dev eth0" in conf and "priority 90" in conf
    assert len(SEC["vrrp"]) == 8


def test_node_certificate_names_its_address():
    from cryptography import x509
    crt, _ = pki.node_cert(SEC["ca_cert"], SEC["ca_key"], "aikos-1", "192.0.2.31")
    san = x509.load_pem_x509_certificate(crt.encode()).extensions.get_extension_for_class(x509.SubjectAlternativeName)
    assert "192.0.2.31" in [str(ip) for ip in san.value.get_values_for_type(x509.IPAddress)]


def test_rollout_decision():
    s = dep.State(current="sha256:a", bad=["sha256:x"])
    assert dep.decide(s, "", True) == "nothing"
    assert dep.decide(s, "sha256:a", True) == "nothing"
    assert dep.decide(s, "sha256:a", False) == "deploy"  # same image but sick: start it again
    assert dep.decide(s, "sha256:x", True) == "skip-bad"
    assert dep.decide(s, "sha256:b", True) == "deploy"


def test_state_survives_a_restart(tmp_path):
    p = tmp_path / "state.json"
    dep.State("sha256:b", "sha256:a", ["sha256:x"]).save(p)
    assert dep.State.load(p) == dep.State("sha256:b", "sha256:a", ["sha256:x"])
    assert dep.State.load(tmp_path / "missing.json") == dep.State()


def test_lock_statement_lets_only_one_node_in():
    """The same SQL the agent sends to rqlite, on SQLite: free → taken; held → refused; expired or own → taken."""
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE deploy_lock(name TEXT PRIMARY KEY, holder TEXT NOT NULL, until INTEGER NOT NULL)")
    sql = ("INSERT INTO deploy_lock(name, holder, until) VALUES ('rollout', ?, ?) ON CONFLICT(name) DO UPDATE SET"
           " holder = excluded.holder, until = excluded.until WHERE deploy_lock.until < ? OR deploy_lock.holder = ?")
    take = lambda node, now: con.execute(sql, (node, now + 600, now, node)).rowcount  # noqa: E731
    assert take("aikos-1", 1000) == 1
    assert take("aikos-2", 1100) == 0
    assert take("aikos-1", 1200) == 1
    assert take("aikos-3", 2000) == 1  # aikos-1 held it until 1800


def test_heartbeat_never_reports_down_for_a_rollout():
    import aikos_heartbeat as hb
    assert hb.node_verdict(200, {"ok": True, "commit": "abcdef1234567", "ha_connected": True}, False)[0] == "up"
    assert hb.node_verdict(200, {"ok": True, "commit": "x", "ha_connected": False}, False) == ("up", "ok x, HA away")
    assert hb.node_verdict(0, {}, True) is None  # rolling: skip the beat, no down
    assert hb.node_verdict(503, {"ok": False, "db": False}, True) is None
    assert hb.node_verdict(0, {}, False) == ("down", "app does not answer")
    assert hb.node_verdict(503, {"ok": False, "db": False}, False) == ("down", "database not reachable")
