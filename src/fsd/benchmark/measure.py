import re

from fsd.benchmark.contracts import BenchmarkError, Measurements, Termination
from fsd.operator.contracts import Event, Reply


class TrialCollector:
  def __init__(self) -> None:
    self._run_id: str | None = None
    self._termination: Termination | None = None
    self._cancellation_recorded = False
    self._counts: dict[str, int] = {
      "help_events": 0,
      "limit_events": 0,
    }

  @property
  def run_id(self) -> str | None:
    return self._run_id

  @property
  def termination(self) -> Termination | None:
    return self._termination

  def measurements(self, duration_seconds: float) -> Measurements:
    return Measurements(
      duration_seconds=duration_seconds,
      **self._counts,
    )

  def _validate_run_id(self, event: Event) -> str | None:
    if event.kind == "progress" and not event.metrics and event.snapshot is None:
      return None

    candidate = (event.metrics or {}).get("run_id")
    if not isinstance(candidate, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", candidate) is None:
      raise BenchmarkError("A benchmark event requires a valid run ID.")

    if self._run_id is not None and candidate != self._run_id:
      raise BenchmarkError("Received an event for a different run.")

    return candidate

  def observe(self, event: Event) -> Reply | None:
    run_id = self._validate_run_id(event)

    if self._termination is not None:
      if (
        self._termination in {"help", "limit"}
        and event.kind == "cancelled"
        and not self._cancellation_recorded
      ):
        self._cancellation_recorded = True
        return None

      raise BenchmarkError("Received an event after the trial had stopped.")

    if run_id is not None:
      self._run_id = run_id

    if event.kind == "help":
      self._termination = "limit" if event.limit else "help"
      self._counts["limit_events" if event.limit else "help_events"] += 1
      return Reply(cancel=True)

    if event.kind == "done":
      self._termination = "done"
    elif event.kind == "failed":
      self._termination = "failed"
    elif event.kind == "cancelled":
      self._termination = "cancelled"

    return None
