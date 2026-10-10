import pytest

Quartz = pytest.importorskip("Quartz", reason="macOS backend needs pyobjc")
ApplicationServices = pytest.importorskip("ApplicationServices", reason="macOS backend needs pyobjc")

from fsd.platform.macos.permissions import check_permissions  # noqa: E402


def _unexpected_permission_request(*args: object, **kwargs: object) -> bool:
  pytest.fail("Permission checks must not request access or display a prompt.")


@pytest.mark.parametrize(
  ("screen_granted", "accessibility_granted", "expected_names"),
  [
    (True, True, []),
    (False, True, ["Screen Recording"]),
    (True, False, ["Accessibility"]),
    (False, False, ["Screen Recording", "Accessibility"]),
  ],
  ids=["both-granted", "screen-missing", "accessibility-missing", "both-missing"],
)
def test_check_permissions_reports_missing_access_without_requesting_it(
  monkeypatch: pytest.MonkeyPatch,
  screen_granted: bool,
  accessibility_granted: bool,
  expected_names: list[str],
) -> None:
  monkeypatch.setattr(Quartz, "CGPreflightScreenCaptureAccess", lambda: screen_granted)
  monkeypatch.setattr(ApplicationServices, "AXIsProcessTrusted", lambda: accessibility_granted)
  monkeypatch.setattr(Quartz, "CGRequestScreenCaptureAccess", _unexpected_permission_request)
  monkeypatch.setattr(
    ApplicationServices, "AXIsProcessTrustedWithOptions", _unexpected_permission_request
  )

  missing = check_permissions()

  assert [permission.name for permission in missing] == expected_names
  for permission in missing:
    assert permission.how_to_grant.strip()
