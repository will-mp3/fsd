import io
import subprocess
import sys
from pathlib import Path

import pytest

from fsd import cli
from fsd.approval.store import ApprovalStore, ApprovalStoreError
from fsd.cli import CliError, resolve_app
from fsd.platform.base import AppInfo, MissingPermission, UnsupportedPlatformError
from fsd.platform.fake import FakePlatform

APPS = [
  AppInfo("com.apple.Notes", "Notes", running=False),
  AppInfo("com.apple.TextEdit", "TextEdit", running=True),
  AppInfo("com.example.TextEdit", "TextEdit", running=False),
  AppInfo("com.apple.dock", "Dock", running=True, system_surface=True),
]


@pytest.fixture
def store(tmp_path: Path) -> ApprovalStore:
  return ApprovalStore(tmp_path / "approvals.json")


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
    (["chat"], {"command": "chat"}),
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
  assert "chat" in captured.out
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


def test_list_apps_shows_every_app_blocked_by_default(store: ApprovalStore) -> None:
  out = io.StringIO()
  assert cli._list_apps(FakePlatform(apps=APPS), store, out) == 0
  header, *rows = out.getvalue().splitlines()
  assert header.split() == ["STATE", "NAME", "BUNDLE", "ID", "NOTE"]
  assert len(rows) == len(APPS)
  assert all(row.split()[0] == "blocked" for row in rows)
  assert {row.split()[2] for row in rows} == {app.bundle_id for app in APPS}


def test_list_apps_uses_bundle_id_approval_and_marks_running_and_system_apps(
  store: ApprovalStore,
) -> None:
  store.approve("com.apple.TextEdit")
  out = io.StringIO()
  assert cli._list_apps(FakePlatform(apps=APPS), store, out) == 0
  rows = [line.split() for line in out.getvalue().splitlines()[1:]]
  by_id = {row[2]: row for row in rows}
  assert by_id["com.apple.TextEdit"] == ["approved", "TextEdit", "com.apple.TextEdit", "running"]
  assert by_id["com.example.TextEdit"] == ["blocked", "TextEdit", "com.example.TextEdit"]
  assert by_id["com.apple.dock"] == ["blocked", "Dock", "com.apple.dock", "system"]
  assert store.approved() == frozenset({"com.apple.TextEdit"})


def test_list_apps_with_empty_inventory_prints_only_header(store: ApprovalStore) -> None:
  out = io.StringIO()
  assert cli._list_apps(FakePlatform(), store, out) == 0
  lines = out.getvalue().splitlines()
  assert len(lines) == 1
  assert lines[0].split() == ["STATE", "NAME", "BUNDLE", "ID", "NOTE"]


@pytest.mark.parametrize(
  ("query", "bundle_id", "name"),
  [
    ("com.apple.Notes", "com.apple.Notes", "Notes"),
    ("nOtEs", "com.apple.Notes", "Notes"),
    ("com.apple.dock", "com.apple.dock", "Dock"),
  ],
)
def test_toggle_approve_persists_resolved_app(
  store: ApprovalStore, tmp_path: Path, query: str, bundle_id: str, name: str
) -> None:
  out = io.StringIO()
  assert cli._toggle(FakePlatform(apps=APPS), store, query, True, out) == 0
  assert store.approved() == frozenset({bundle_id})
  assert ApprovalStore(tmp_path / "approvals.json").approved() == frozenset({bundle_id})
  assert out.getvalue() == f"Approved {name} ({bundle_id}).\n"


def test_toggle_block_persists_removal_and_preserves_other_approvals(
  store: ApprovalStore, tmp_path: Path
) -> None:
  store.approve("com.apple.Notes")
  store.approve("com.apple.TextEdit")
  out = io.StringIO()
  assert cli._toggle(FakePlatform(apps=APPS), store, "Notes", False, out) == 0
  assert store.approved() == frozenset({"com.apple.TextEdit"})
  assert ApprovalStore(tmp_path / "approvals.json").approved() == store.approved()
  assert out.getvalue() == "Blocked Notes (com.apple.Notes).\n"


@pytest.mark.parametrize("query", ["TextEdit", "Nonexistent"])
@pytest.mark.parametrize("approve", [True, False])
def test_toggle_invalid_target_leaves_approvals_unchanged(
  store: ApprovalStore, tmp_path: Path, query: str, approve: bool
) -> None:
  store.approve("com.apple.Notes")
  path = tmp_path / "approvals.json"
  original = path.read_bytes()
  out = io.StringIO()
  with pytest.raises(CliError):
    cli._toggle(FakePlatform(apps=APPS), store, query, approve, out)
  assert store.approved() == frozenset({"com.apple.Notes"})
  assert path.read_bytes() == original
  assert out.getvalue() == ""


@pytest.mark.parametrize("approve", [True, False])
def test_toggle_failed_save_does_not_print_success(tmp_path: Path, approve: bool) -> None:
  parent = tmp_path / "config"
  store = ApprovalStore(parent / "approvals.json")
  parent.write_text("A file prevents creation of the config directory.", encoding="utf-8")
  out = io.StringIO()
  with pytest.raises(ApprovalStoreError, match="Could not write approvals"):
    cli._toggle(FakePlatform(apps=APPS), store, "Notes", approve, out)
  assert out.getvalue() == ""


@pytest.mark.parametrize("missing", [False, True])
def test_run_doctor_reports_status_without_loading_approvals(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing: bool
) -> None:
  monkeypatch.setenv("FSD_CONFIG_DIR", str(tmp_path))
  (tmp_path / "approvals.json").write_text("invalid json", encoding="utf-8")
  permissions = [MissingPermission("Screen Recording", "System Settings")] if missing else []
  fake = FakePlatform(missing_permissions=permissions)
  out, err = io.StringIO(), io.StringIO()
  code = cli.run(["doctor"], backend_factory=lambda: fake, out=out, err=err)
  assert code == (1 if missing else 0)
  assert "Capabilities:" in out.getvalue()
  assert err.getvalue() == ""


def test_run_lists_apps_with_injected_store(store: ApprovalStore) -> None:
  store.approve("com.apple.Notes")
  out, err = io.StringIO(), io.StringIO()
  code = cli.run(
    ["apps", "list"],
    backend_factory=lambda: FakePlatform(apps=APPS),
    store=store,
    out=out,
    err=err,
  )
  assert code == 0
  row = next(line for line in out.getvalue().splitlines() if "com.apple.Notes" in line)
  assert row.startswith("approved")
  assert err.getvalue() == ""


def test_chat_needs_no_model_argument(
  store: ApprovalStore, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
  monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
  monkeypatch.setattr("builtins.input", lambda prompt: "/exit")
  platform = FakePlatform()
  out, err = io.StringIO(), io.StringIO()

  code = cli.run(["chat"], backend_factory=lambda: platform, store=store, out=out, err=err)

  assert code == 0
  assert "enter a goal" in out.getvalue()
  assert err.getvalue() == ""
  assert platform.capture_requests == []
  assert platform.actions == []
  captured = capsys.readouterr()
  assert captured.out == ""
  assert captured.err == ""


def test_chat_reports_missing_credentials_through_cli(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
  monkeypatch.setenv("FSD_CONFIG_DIR", str(tmp_path))
  platform = FakePlatform()
  out, err = io.StringIO(), io.StringIO()

  code = cli.run(["chat"], backend_factory=lambda: platform, out=out, err=err)

  assert code == 2
  assert "OPENROUTER_API_KEY" in err.getvalue()
  assert "Traceback" not in err.getvalue()
  assert out.getvalue() == ""
  assert platform.capture_requests == []
  assert platform.actions == []


@pytest.mark.parametrize("command", ["approve", "block"])
def test_run_updates_default_store(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
  monkeypatch.setenv("FSD_CONFIG_DIR", str(tmp_path))
  path = tmp_path / "approvals.json"
  if command == "block":
    ApprovalStore(path).approve("com.apple.Notes")
  out, err = io.StringIO(), io.StringIO()
  code = cli.run(
    ["apps", command, "Notes"],
    backend_factory=lambda: FakePlatform(apps=APPS),
    out=out,
    err=err,
  )
  assert code == 0
  assert ApprovalStore(path).is_approved("com.apple.Notes") == (command == "approve")
  verb = "Approved" if command == "approve" else "Blocked"
  assert out.getvalue() == f"{verb} Notes (com.apple.Notes).\n"
  assert err.getvalue() == ""


@pytest.mark.parametrize("query", ["TextEdit", "Nonexistent"])
def test_run_reports_resolution_errors_without_changing_approvals(
  store: ApprovalStore, query: str
) -> None:
  out, err = io.StringIO(), io.StringIO()
  code = cli.run(
    ["apps", "approve", query],
    backend_factory=lambda: FakePlatform(apps=APPS),
    store=store,
    out=out,
    err=err,
  )
  assert code == 2
  assert err.getvalue().startswith("fsd: ")
  assert query in err.getvalue()
  assert "Traceback" not in err.getvalue()
  assert out.getvalue() == ""
  assert store.approved() == frozenset()


def test_run_reports_backend_selection_error() -> None:
  def refuse() -> FakePlatform:
    raise UnsupportedPlatformError("This backend is unavailable.")

  out, err = io.StringIO(), io.StringIO()
  assert cli.run(["doctor"], backend_factory=refuse, out=out, err=err) == 2
  assert err.getvalue() == "fsd: This backend is unavailable.\n"
  assert out.getvalue() == ""


def test_run_reports_corrupt_default_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.setenv("FSD_CONFIG_DIR", str(tmp_path))
  path = tmp_path / "approvals.json"
  path.write_text("invalid json", encoding="utf-8")
  out, err = io.StringIO(), io.StringIO()
  code = cli.run(
    ["apps", "list"],
    backend_factory=FakePlatform,
    out=out,
    err=err,
  )
  assert code == 2
  assert err.getvalue().startswith("fsd: ")
  assert "unreadable" in err.getvalue()
  assert "Traceback" not in err.getvalue()
  assert out.getvalue() == ""
  assert path.read_text(encoding="utf-8") == "invalid json"


def test_run_reports_save_failure_without_success_message(tmp_path: Path) -> None:
  parent = tmp_path / "config"
  store = ApprovalStore(parent / "approvals.json")
  parent.write_text("Not a directory.", encoding="utf-8")
  out, err = io.StringIO(), io.StringIO()
  code = cli.run(
    ["apps", "approve", "Notes"],
    backend_factory=lambda: FakePlatform(apps=APPS),
    store=store,
    out=out,
    err=err,
  )
  assert code == 2
  assert err.getvalue().startswith("fsd: Could not write approvals")
  assert out.getvalue() == ""


def test_run_defaults_to_standard_output(capsys: pytest.CaptureFixture[str]) -> None:
  assert cli.run(["doctor"], backend_factory=FakePlatform) == 0
  captured = capsys.readouterr()
  assert "All required permissions are granted." in captured.out
  assert captured.err == ""


def test_run_help_does_not_construct_backend(capsys: pytest.CaptureFixture[str]) -> None:
  def unexpected_backend() -> FakePlatform:
    pytest.fail("Help must work without constructing a platform backend.")

  with pytest.raises(SystemExit) as exc_info:
    cli.run(["--help"], backend_factory=unexpected_backend)
  assert exc_info.value.code == 0
  assert "usage: fsd" in capsys.readouterr().out


@pytest.mark.parametrize(
  ("argv", "expected_status"),
  [(["--help"], 0), ([], 2), (["apps", "approve"], 2)],
)
def test_main_reads_process_arguments_and_exits_with_expected_status(
  argv: list[str], expected_status: int, tmp_path: Path
) -> None:
  result = subprocess.run(
    [sys.executable, "-c", "from fsd.cli import main; main()", *argv],
    cwd=tmp_path,
    capture_output=True,
    text=True,
    timeout=10,
    check=False,
  )
  assert result.returncode == expected_status
  if expected_status == 0:
    assert "usage: fsd" in result.stdout
    assert "doctor" in result.stdout
    assert result.stderr == ""
  else:
    assert "usage: fsd" in result.stderr
    assert "error:" in result.stderr
    assert "Traceback" not in result.stderr
    assert result.stdout == ""
