"""Command line: `python -m aikos_app` serves; the other commands need shell access to the server (that proves ownership).

    serve                     run the app (default)
    setup-code                print a fresh one-time setup code while nobody is set up yet
    device-invite <id|name>   print a link that adds a passkey to an existing person (lost or new phone)
    people                    list people (id, name, role)
"""

from __future__ import annotations

import argparse
import logging
import sys

from aiohttp import web

from .api.server import build_context, create_app
from .config import from_env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aikos_app", description="aikos app")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("serve")
    sub.add_parser("setup-code")
    dev = sub.add_parser("device-invite")
    dev.add_argument("person")
    sub.add_parser("people")
    args = parser.parse_args(argv)
    settings = from_env()

    if args.cmd in (None, "serve"):
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        web.run_app(create_app(settings), host=settings.listen_host, port=settings.port, print=None)
        return 0

    c = build_context(settings)
    if args.cmd == "setup-code":
        code = c.auth.new_setup_code()
        print(code if code else "Already set up; use device-invite to add a passkey.", file=sys.stdout)
        return 0 if code else 1
    if args.cmd == "people":
        for u in c.accounts.list_users():
            print(f"{u.id}\t{u.name}\t{u.role}{'\t(disabled)' if u.disabled else ''}")
        return 0
    if args.cmd == "device-invite":
        users = c.accounts.list_users()
        match = [u for u in users if str(u.id) == args.person or u.name.casefold() == args.person.casefold()]
        if len(match) != 1:
            print("No unique person with that id or name.", file=sys.stderr)
            return 1
        token, _ = c.auth.device_invite(match[0].id)
        print(f"{settings.public_url}/einladung#{token}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
