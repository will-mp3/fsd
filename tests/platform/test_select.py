import sys

import pytest

from fsd.platform import require_mandatory, select_backend
from fsd.platform.base import Capability, UnsupportedPlatformError
from fsd.platform.fake import FakePlatform


def test_unknown_system_is_refused_with_an_explanation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(UnsupportedPlatformError, match="Only macOS is supported"):
        select_backend()


def test_backend_with_all_mandatory_capabilities_is_accepted() -> None:
    fake = FakePlatform()
    assert require_mandatory(fake) is fake


@pytest.mark.parametrize(
    "present, missing_name",
    [
        ({Capability.FILTERED_CAPTURE}, "window_owner_lookup"),
        ({Capability.WINDOW_OWNER_LOOKUP}, "filtered_capture"),
    ],
)
def test_backend_missing_a_mandatory_capability_is_refused(
    present: set[Capability], missing_name: str
) -> None:
    with pytest.raises(UnsupportedPlatformError, match=missing_name):
        require_mandatory(FakePlatform(capabilities=present))
