"""Writes the LaunchAgents of the aikos transcriber on a Mac, one per side (room, door).

    /usr/bin/python3 deploy/launchd.py --env ~/.aikos/transcriber.env --checkout ~/aikos/repo
    /usr/bin/python3 deploy/launchd.py --env ~/.aikos/transcriber.env --import-from <existing agent plists>

The house settings live in the env file, never in the repository (see transcriber.env.example): one AIKOS_KEY=value
per line, "#" starts a comment line. Each agent gets them plus its AIKOS_SIDE. --import-from creates the env file once
from the existing transcriber agents; they must agree (mode 600; an existing env file is never overwritten).
Called by deploy.sh.
"""
from __future__ import annotations

import argparse
import os
import plistlib
import shlex
from pathlib import Path

LABEL = "home.aikos.transcriber.{side}"
SIDES = ("room", "door")
PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
PER_SIDE = ("AIKOS_SIDE", "AIKOS_PORT")   # would apply to both agents: each side keeps its own default


def read_env(path: Path) -> dict:
    env = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not key.startswith("AIKOS_"):
            raise ValueError(f"{path}: not an AIKOS_ setting: {key!r}")
        if key in PER_SIDE:
            raise ValueError(f"{path}: {key} is set per side, not in the shared settings")
        env[key] = value.strip()
    return env


def imported(*plists: Path) -> dict:
    """The shared AIKOS_ settings of existing agents (without the per-side ones). Agents that disagree: ValueError."""
    first: dict | None = None
    for plist in plists:
        with open(plist, "rb") as f:
            env = plistlib.load(f).get("EnvironmentVariables", {})
        env = {k: v for k, v in env.items() if k.startswith("AIKOS_") and k not in PER_SIDE}
        if first is not None and env != first:
            key = sorted(set(env.items()) ^ set(first.items()))[0][0]
            raise ValueError(f"{plist}: {key} differs between the agents; write the env file by hand")
        first = env
    return first or {}


def write_env(path: Path, env: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = ("# aikos transcriber: settings of this house (taken over by deploy/launchd.py --import-from)\n"
            + "".join(f"{k}={v}\n" for k, v in sorted(env.items())))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)


def agent(side: str, env: dict, checkout: Path, logs: Path, python: str = "/usr/bin/python3") -> dict:
    if side not in SIDES:
        raise ValueError(f"side must be one of {SIDES}")
    log = logs / f"transcriber-{side}.log"
    return {
        "Label": LABEL.format(side=side),
        "ProgramArguments": ["/bin/bash", "-c",
                             f"exec {shlex.quote(python)} -u -m aikos_transcriber >> {shlex.quote(str(log))} 2>&1"],
        "WorkingDirectory": str(checkout / "services" / "transcriber"),
        "EnvironmentVariables": {**env, "AIKOS_SIDE": side, "PATH": PATH},
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "ProcessType": "Interactive",
    }


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--env", type=Path, required=True, help="the house settings (KEY=value)")
    ap.add_argument("--checkout", type=Path, help="the aikos repository checkout the agents run from")
    ap.add_argument("--agents", type=Path, default=Path("~/Library/LaunchAgents").expanduser())
    ap.add_argument("--logs", type=Path, default=Path("~/Library/Logs/aikos").expanduser())
    ap.add_argument("--python", default="/usr/bin/python3")
    ap.add_argument("--import-from", type=Path, nargs="+", help="create --env from these existing agent plists")
    a = ap.parse_args(argv)
    if a.import_from:
        write_env(a.env.expanduser(), imported(*a.import_from))
        print(f"settings written to {a.env}")
        return
    if not a.checkout:
        ap.error("--checkout is required")
    env = read_env(a.env.expanduser())
    a.logs.mkdir(parents=True, exist_ok=True)
    for side in SIDES:
        path = a.agents / f"{LABEL.format(side=side)}.plist"
        with open(path, "wb") as f:
            plistlib.dump(agent(side, env, a.checkout.expanduser().resolve(), a.logs, a.python), f)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
