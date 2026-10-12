"""The fsd command line: environment checks and per-app approval."""

import argparse
from collections.abc import Sequence
from typing import TextIO

from fsd.platform.base import AppInfo, Platform


class CliError(Exception):
  """A user-correctable problem that the CLI can report without a traceback."""


def resolve_app(query: str, apps: Sequence[AppInfo]) -> AppInfo:
  """Match an exact bundle indentifier or a unique case-insensitive name."""
  for app in apps:
    if app.bundle_id == query:
      return app

  matches = [app for app in apps if app.name.casefold() == query.casefold()]
  if not matches:
    raise CliError(f"No app matches '{query}'. Run 'fsd apps list' to see the choices.")
  if len(matches) > 1:
    candidates = ", ".join(app.bundle_id for app in matches)
    raise CliError(f"'{query}' matches more than one app. Use a bundle identifier: {candidates}.")
  return matches[0]


def _build_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(
    prog="fsd", description="Operate desktop applications under per-app approval."
  )
  commands = parser.add_subparsers(dest="command", required=True)
  commands.add_parser("doctor", help="check capabilities and OS permissions")

  apps = commands.add_parser("apps", help="list applications and change their approval")
  apps_commands = apps.add_subparsers(dest="apps_command", required=True)
  apps_commands.add_parser("list", help="show every app with its approval state")

  for name, summary in (
    ("approve", "allow fsd to see and control an app"),
    ("block", "stop fsd from seeing and controlling an app"),
  ):
    command = apps_commands.add_parser(name, help=summary)
    command.add_argument("app", help="bundle identifier or display name")

  return parser


def _doctor(platform: Platform, out: TextIO) -> int:
  capabilities = ", ".join(sorted(capability.value for capability in platform.capabilities))
  print(f"Capabilities: {capabilities}", file=out)

  missing = platform.check_permissions()
  if not missing:
    print("All required permissions are granted.", file=out)
    return 0

  for permission in missing:
    print(f"Missing permission: {permission.name}", file=out)
    print(f"  Grant it in: {permission.how_to_grant}", file=out)
  return 1
