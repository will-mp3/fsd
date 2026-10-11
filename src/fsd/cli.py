"""The fsd command line: environment checks and per-app approval."""

from collections.abc import Sequence

from fsd.platform.base import AppInfo


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
