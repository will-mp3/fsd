from fsd.benchmark.contracts import BenchmarkError, Termination
from fsd.operator.contracts import Event, Reply


class TrialCollector:
  def __init__(self) -> None:
    self._termination: Termination | None = None
    self._cancellation_recorded = False

  @property
  def termination(self) -> Termination | None:
    return self._termination

  def observe(self, event: Event) -> Reply | None:
    if self._termination is not None:
      if (
        self._termination in {"help", "limit"}
        and event.kind == "cancelled"
        and not self._cancellation_recorded
      ):
        self._cancellation_recorded = True
        return None

      raise BenchmarkError("Received an event after the trial had stopped.")

    if event.kind == "help":
      self._termination = "limit" if event.limit else "help"
      return Reply(cancel=True)

    if event.kind == "done":
      self._termination = "done"
    elif event.kind == "failed":
      self._termination = "failed"
    elif event.kind == "cancelled":
      self._termination = "cancelled"

    return None
