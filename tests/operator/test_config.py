from fsd.operator.config import Settings


def test_default_model_does_not_require_cli_input() -> None:
  assert Settings().model == "google/gemini-3.1-flash-lite"
