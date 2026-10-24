"""Operator commands. `python -m backend.cli create-admin EMAIL [--name NAME]`

The password is prompted for (or read from stdin when it is not a terminal). Safe to run next to
a live server: it does not take the data-dir lock, and SQLite serializes the write.
"""

import argparse
import getpass
import sys

from backend.core import db, settings
from backend.core.auth import bootstrap


def _password() -> str:
    if not sys.stdin.isatty():
        return sys.stdin.readline().rstrip("\n")
    first = getpass.getpass("Password: ")
    if first != getpass.getpass("Again: "):
        sys.exit("Passwords do not match.")
    return first


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m backend.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-admin", help="create an admin account")
    create.add_argument("email")
    create.add_argument("--name", default="")
    args = parser.parse_args(argv)

    db.init(settings.data_dir(), lock=False)
    db.migrate()
    user = bootstrap.create_admin(args.email, args.name, _password())
    print(f"Created admin {user['email']} (id {user['id']}).")


if __name__ == "__main__":
    main()
