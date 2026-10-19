import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from fsd.operator.client import DecisionClient, InferenceError
from fsd.operator.config import Settings
from fsd.operator.context import Observation
from fsd.operator.contracts import Decision
from fsd.operator.control import Control
from fsd.platform.base import Frame


@dataclass(frozen=True)
class Case:
  name: str
  context: str
  frame: Frame


Assessment = Callable[[Case, Decision], bool | None]


async def evaluate(
  cases: Sequence[Case],
  client: DecisionClient,
  settings: Settings,
  assess: Assessment | None = None,
) -> list[dict[str, object]]:
  rows: list[dict[str, object]] = []

  for case in cases:
    started = time.monotonic()
    observation = Observation(case.frame, None, case.context, started)

    try:
      result = await client.decide(observation, Control())
    except InferenceError as exc:
      rows.append(
        {
          "case": case.name,
          "model": settings.model,
          "valid": False,
          "seconds": time.monotonic() - started,
          "error": type(exc).__name__,
          "cost": None,
          "correct": None,
        }
      )
    else:
      action = result.decision.action
      rows.append(
        {
          "case": case.name,
          "model": settings.model,
          "valid": True,
          "seconds": time.monotonic() - started,
          "decision": result.decision.kind,
          "action": action.kind if action else None,
          "input_tokens": result.input_tokens,
          "output_tokens": result.output_tokens,
          "cost": result.cost,
          "correct": assess(case, result.decision) if assess is not None else None,
        }
      )

  return rows
