import io

import pytest

from fsd import cli
from fsd.cli import CliError, resolve_app
from fsd.platform.base import AppInfo, MissingPermission
from fsd.platform.fake import FakePlatform

APPS = [
  AppInfo("com.apple.Notes", "Notes", running=False),
  AppInfo("com.apple.TextEdit", "TextEdit", running=True),
  AppInfo("com.example.TextEdit", "TextEdit", running=False),
]


def test_resolve_exact_bundle_id_disambiguates_duplicate_names() -> None:
  assert resolve_app("com.apple.TextEdit", APPS) == APPS[1]


def test_resolve_bundle_id_takes_priority_over_another_apps_name() -> None:
  impostor = AppInfo("com.example.other", "com.apple.Notes", running=False)
  assert resolve_app("com.apple.Notes", [impostor, *APPS]) == APPS[0]


def test_resolve_unique_name_ignores_case() -> None:
  assert resolve_app("nOtEs", APPS) == APPS[0]


def test_resolve_ambiguous_name_lists_candidates() -> None:
  with pytest.raises(CliError) as exc_info:
    resolve_app("textedit", APPS)
  message = str(exc_info.value)
  assert "more than one app" in message
  assert "com.apple.TextEdit" in message
  assert "com.example.TextEdit" in message


@pytest.mark.parametrize("query", ["Nonexistent", "Note", "COM.APPLE.NOTES"])
def test_resolve_unknown_partial_or_inexact_identifier_is_refused(query: str) -> None:
  with pytest.raises(CliError) as exc_info:
    resolve_app(query, APPS)
  assert f"No app matches '{query}'" in str(exc_info.value)
  assert "fsd apps list" in str(exc_info.value)


def test_resolve_empty_app_list_is_refused() -> None:
  with pytest.raises(CliError, match="No app matches"):
    resolve_app("Notes", [])


@pytest.mark.parametrize(
  ("argv", "expected"),
  [
    (["doctor"], {"command": "doctor"}),
    (["apps", "list"], {"command": "apps", "apps_command": "list"}),
    (
      ["apps", "approve", "Notes"],
      {"command": "apps", "apps_command": "approve", "app": "Notes"},
    ),
    (
      ["apps", "block", "com.apple.Notes"],
      {"command": "apps", "apps_command": "block", "app": "com.apple.Notes"},
    ),
  ],
)
def test_parser_accepts_supported_commands(argv: list[str], expected: dict[str, str]) -> None:
  args = cli._build_parser().parse_args(argv)
  assert vars(args) == expected


@pytest.mark.parametrize(
  "argv", [[], ["apps"], ["apps", "approve"], ["apps", "block"], ["unknown"]]
)
def test_parser_rejects_incomplete_or_unknown_commands(
  argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
  with pytest.raises(SystemExit) as exc_info:
    cli._build_parser().parse_args(argv)
  assert exc_info.value.code == 2
  captured = capsys.readouterr()
  assert "usage: fsd" in captured.err
  assert "error:" in captured.err
  assert captured.out == ""


def test_parser_help_lists_commands_and_exits_successfully(
  capsys: pytest.CaptureFixture[str],
) -> None:
  with pytest.raises(SystemExit) as exc_info:
    cli._build_parser().parse_args(["--help"])
  assert exc_info.value.code == 0
  captured = capsys.readouterr()
  assert "doctor" in captured.out
  assert "apps" in captured.out
  assert captured.err == ""


def test_doctor_reports_capabilities_and_success_to_supplied_stream(
  capsys: pytest.CaptureFixture[str],
) -> None:
  out = io.StringIO()
  code = cli._doctor(FakePlatform(), out)
  assert code == 0
  assert "Capabilities: filtered_capture, window_owner_lookup" in out.getvalue()
  assert "All required permissions are granted." in out.getvalue()
  captured = capsys.readouterr()
  assert captured.out == ""
  assert captured.err == ""


@pytest.mark.parametrize("count", [1, 2])
def test_doctor_reports_every_missing_permission_and_returns_one(count: int) -> None:
  permissions = [
    MissingPermission("Screen Recording", "System Settings > Privacy > Screen Recording"),
    MissingPermission("Accessibility", "System Settings > Privacy > Accessibility"),
  ][:count]
  out = io.StringIO()
  code = cli._doctor(FakePlatform(missing_permissions=permissions), out)
  assert code == 1
  report = out.getvalue()
  for permission in permissions:
    assert f"Missing permission: {permission.name}" in report
    assert f"Grant it in: {permission.how_to_grant}" in report
  assert "All required permissions are granted." not in report
