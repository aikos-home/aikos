# aikos cluster: the app on three nodes

Runs the aikos app on three small Linux VMs (one per hypervisor host) so that losing a host, a VM or a rollout never
takes the app away. Generic: every house value comes from an inventory file you keep private.

```
phone ─► reverse proxy (or DNS straight to the virtual address) ─► virtual address (keepalived)
                                                                       │ follows a healthy node
                   ┌───────────────────────────────┬───────────────────┴───────────┐
               node 1                          node 2                          node 3
   Caddy :443 → app 127.0.0.1:8780   (same)                           (same)
   rqlite :4001 HTTPS / :4002 Raft ◄── mutual TLS between the three ──►
   rollout agent (every minute)   backup (hourly)   keepalived
```

## What runs on a node

| Part | How | Listens |
|---|---|---|
| app | container, image pinned by digest, started only by the rollout agent | `127.0.0.1:8780` |
| rqlite 10.5.2 | container | `<node>:4001` HTTPS API (users with rights), `<node>:4002` Raft (mutual TLS, own CA) |
| Caddy 2.10.2 | container | `:80`, `:443` for the domain; `http://<node>/api/v1/health` (by address, for the peers) |
| keepalived | host package | unicast VRRP to the two peers, moves the virtual address to a healthy node, `nopreempt` |
| `aikos-deployer.timer` | systemd, every minute | rolls out new images (below) |
| `aikos-db-backup.timer` | systemd, hourly at :05 | consistent copy of the database to `/var/backups/aikos/aikos-app.sqlite` |

All containers use the host network: ports published by Docker would bypass the host firewall.

## Rollout (every merge to `main`)

1. The workflow `app-image` builds `ghcr.io/aikos-home/aikos-app`, smoke-tests it, pushes `:main` and
   `:sha-<commit>`, and signs the digest with cosign (keyless; the signature names the workflow and `refs/heads/main`).
2. On every node, every minute, `aikos_deployer.py` asks the registry where `:main` points. Nothing comes in from
   GitHub; there is no self-hosted runner on the public repository.
3. A new digest is checked with `cosign verify` against exactly that workflow identity. Unsigned or foreign: marked bad.
4. The node takes the cluster-wide lock (one row in rqlite, `INSERT … ON CONFLICT … WHERE`, 10 min lease). Only one
   node changes at a time. If one of the other nodes is not healthy, it waits: a rollout never leaves one node alone.
5. If it holds the virtual address, it hands it over first (its health check fails while it rolls out; a peer takes
   the address in about 2 s), so a planned rollout has no gap.
6. It starts the new image and waits up to 120 s for `/api/v1/health` with `ok: true` and the commit from the image's
   `org.opencontainers.image.revision` label. Not healthy: back to the previous digest, the new one is marked bad.

State per node: `/var/lib/aikos/deployer/state.json` (current, previous, bad). Logs: `journalctl -u aikos-deployer`.

**Private image:** if the package in the registry is private, put a read-only token in a file on the admin machine and
name it in the inventory (`[registry]`, see the example). `apply.py` logs root's Docker on every node in with it (token on
stdin only, stored in `/root/.docker/config.json`, 0600); pulls, the registry lookup and `cosign verify` then use it.
For GHCR that is a classic token with only `read:packages`. If it expires, rollouts stop (the running version stays).

## Setting up or changing nodes

```sh
python deploy/cluster/apply.py --inventory /path/to/private/cluster.toml --check   # reachable, sudo works
python deploy/cluster/apply.py --inventory /path/to/private/cluster.toml           # bring all three to the state
```

Needs SSH (key) as a user with sudo, Docker with the compose plugin, Python 3 on the nodes; Python 3.11+ and
`cryptography` on the admin machine. Idempotent. Shared secrets (database users, VRRP password, the cluster CA) are
generated on the first run and exist only on the nodes (`/etc/aikos/secrets/cluster.json`, root, 0400); later runs read
them back from a node, so a rebuilt node gets the same ones. Nothing is printed. `--rotate-certs` issues new node
certificates. Template for the inventory: [`cluster.example.toml`](cluster.example.toml).

## Files on a node

| Path | Owner, mode | What |
|---|---|---|
| `/opt/aikos/compose.yaml`, `/etc/aikos/Caddyfile` | root 0644 | from this folder |
| `/etc/aikos/cluster.env`, `/etc/aikos/app.env` | root 0644 | node and app settings, no secrets |
| `/etc/aikos/app-image.env` | root | the digest the rollout agent runs |
| `/etc/aikos/certs/` | `node.key` rqlite 0400 | cluster CA certificate, this node's certificate |
| `/etc/aikos/secrets/` | 0711; files 0400 | `cluster.json` (root), `rqlite-auth.json` (rqlite), `app/` (app: database password, Home Assistant token), `deployer.env`, `backup.env` |
| `/var/lib/aikos/{rqlite,app,caddy,deployer}` | per service, 0700 | data |
| `/var/backups/aikos/` | root:aikos 0750 | `aikos-app.sqlite` (0640), `.sha256`, `last-ok` |

## Failure cases

| What happens | Effect |
|---|---|
| One node, VM or host down | keepalived moves the address in about 2–3 s (measured 21.10. with the old 2 s interval: 4 s); rqlite keeps a majority; rollouts wait until it is back |
| Two nodes down | rqlite has no majority: the app cannot write (no sign-in); the remaining node keeps the address only if healthy |
| New image does not start | that node rolls back by itself, marks the digest bad; the other two never take it |
| Registry or GitHub unreachable | nothing changes; the running version stays |
| Home Assistant away | the app runs and says so; it does not move the address (all nodes would see the same) |

## Restore the database

Stop the app on all nodes, then load a backup into the cluster with rqlite's restore (`/boot` on a fresh cluster or
`/db/load`), see the rqlite documentation. Passkeys live only here: keep the hourly backups.
