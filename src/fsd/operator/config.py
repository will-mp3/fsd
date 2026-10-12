from dataclasses import dataclass

from fsd.platform.base import MAX_HOLD_MS

MAX_WAIT_MS = 5000


@dataclass(frozen=True)
class Settings:
  model: str = "google/gemini-3.1-flash-lite"
  api_url: str = "https://openrouter.ai/api/v1/chat/completions"
  max_hold_ms: int = MAX_HOLD_MS
  max_wait_ms: int = MAX_WAIT_MS
  history_size: int = 20
  action_limit: int = 1000
  active_seconds: float = 3600
  request_seconds: float = 60
  retries: int = 2
  recovery_limit: int = 3
  max_output_tokens: int = 1024
