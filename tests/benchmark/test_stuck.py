from fsd.benchmark.measure import TrialCollector
from fsd.operator.contracts import Event, Reply
from tests.benchmark.helpers import step_event


def test_only_new_stuck_signals_count_when_warning_text_persists() -> None:
  collector = TrialCollector()
  warning = "No visible progress."
  collector.observe(
    step_event(0, attempts=(("decision", "completed"),), stuck="warn", warning=warning)
  )
  assert collector.measurements(duration_seconds=1.0).stuck_warnings == 1

  collector.observe(step_event(1, attempts=(("decision", "completed"),), warning=warning))
  collector.observe(Event("progress", warning))
  assert collector.measurements(duration_seconds=2.0).stuck_warnings == 1

  collector.observe(
    step_event(2, attempts=(("decision", "completed"),), stuck="warn", warning=warning)
  )
  result = collector.measurements(duration_seconds=3.0)

  assert result.stuck_warnings == 2
  assert result.stuck_escalations == 0
  assert result.captured_steps == 3


def test_stuck_escalation_and_help_are_counted_from_their_separate_events() -> None:
  collector = TrialCollector()
  collector.observe(step_event(0, attempts=(("decision", "completed"),), stuck="warn"))
  collector.observe(step_event(1, attempts=(), outcome="help", stuck="escalate"))
  before_help = collector.measurements(duration_seconds=1.0)

  assert before_help.stuck_warnings == 1
  assert before_help.stuck_escalations == 1
  assert before_help.help_events == 0
  assert collector.termination is None

  reply = collector.observe(Event("help", "Guidance needed", metrics={"run_id": "run"}))
  assert reply == Reply(cancel=True)
  collector.observe(Event("cancelled", "Stopped", metrics={"run_id": "run"}))
  stopped = collector.measurements(duration_seconds=2.0)

  assert stopped.stuck_warnings == 1
  assert stopped.stuck_escalations == 1
  assert stopped.help_events == 1
  assert collector.termination == "help"


def test_stuck_metric_without_a_finalized_capture_does_not_increment_counts() -> None:
  collector = TrialCollector()
  collector.observe(Event("metrics", "Totals", metrics={"run_id": "run", "stuck": "warn"}))

  result = collector.measurements(duration_seconds=1.0)

  assert result.stuck_warnings == 0
  assert result.stuck_escalations == 0
  assert result.captured_steps == 0
