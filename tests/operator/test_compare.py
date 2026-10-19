import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from fsd.operator import evaluate as evaluation
from fsd.operator.contracts import Decision
from fsd.operator.evaluate import Case, compare
from fsd.platform.base import Frame, Rect
from tests.operator.helpers import decision


@pytest.mark.parametrize("invalid_first", [False, True])
def test_comparison_preserves_inputs_and_runs_sequentially(
  monkeypatch: pytest.MonkeyPatch, invalid_first: bool
) -> None:
  cases = [
    Case("one", "first task", Frame(b"first", 100, 100, Rect(0, 0, 100, 100))),
    Case("two", "second task", Frame(b"second", 200, 100, Rect(0, 0, 200, 100))),
  ]
  requests: list[dict[str, object]] = []
  assessed: list[str] = []
  active = 0
  peak_active = 0

  async def handle(request: httpx.Request) -> httpx.Response:
    nonlocal active, peak_active
    active += 1
    peak_active = max(peak_active, active)
    requests.append(json.loads(request.content))
    index = len(requests) - 1
    try:
      await asyncio.sleep(0)
      content = "invalid" if invalid_first and index == 0 else decision().model_dump_json()
      return httpx.Response(
        200,
        json={
          "choices": [{"finish_reason": "stop", "message": {"content": content}}],
          "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.0001},
        },
      )
    finally:
      active -= 1

  def assess(case: Case, choice: Decision) -> bool:
    assessed.append(case.name)
    return case.name == "two"

  http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
  monkeypatch.setattr(evaluation, "httpx", SimpleNamespace(AsyncClient=lambda: http))

  rows = asyncio.run(compare(cases, ["model-a", "model-b"], "test-key", assess))

  assert [(row["model"], row["case"]) for row in rows] == [
    ("model-a", "one"),
    ("model-a", "two"),
    ("model-b", "one"),
    ("model-b", "two"),
  ]
  assert [row["valid"] for row in rows] == [not invalid_first, True, True, True]
  assert [row["correct"] for row in rows] == [None if invalid_first else False, True, False, True]
  assert assessed == (["two", "one", "two"] if invalid_first else ["one", "two", "one", "two"])
  assert [body["model"] for body in requests] == ["model-a", "model-a", "model-b", "model-b"]
  assert peak_active == 1
  for first, second in zip(requests[:2], requests[2:], strict=True):
    assert {key: value for key, value in first.items() if key != "model"} == {
      key: value for key, value in second.items() if key != "model"
    }
  assert requests[0]["messages"] != requests[1]["messages"]
  assert http.is_closed
