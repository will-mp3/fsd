import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from fsd.operator import client as client_module
from fsd.operator.config import Settings
from fsd.operator.context import SYSTEM_PROMPT, Observation
from fsd.operator.control import Control
from fsd.platform.base import Frame, Rect


def frame(data: bytes) -> Frame:
  return Frame(data, 100, 100, Rect(0, 0, 100, 100))


def response_body(content: str) -> dict[str, object]:
  return {
    "choices": [{"finish_reason": "stop", "message": {"content": content}}],
    "usage": {"prompt_tokens": 100, "completion_tokens": 30, "cost": 0.001},
  }


def done_content() -> str:
  return json.dumps(
    {
      "kind": "done",
      "action": None,
      "message": "Complete",
      "expected": "",
      "notes": "",
      "previous_result": "success",
    }
  )


@pytest.mark.parametrize(
  ("payload", "expected"),
  [({}, None), ({"prompt_tokens": 100}, None), ({"cost": 0}, 0.0)],
)
def test_usage_distinguishes_unreported_cost_from_free(
  payload: dict[str, object], expected: float | None
) -> None:
  from fsd.operator.client import Usage

  assert Usage.model_validate(payload).cost == expected


@pytest.mark.parametrize("with_previous", [False, True])
@pytest.mark.parametrize("correction", ["", "Return a valid decision."])
def test_request_body_labels_images_and_requires_schema(
  with_previous: bool, correction: str
) -> None:
  from fsd.operator.client import request_body

  observation = Observation(frame(b"png"), frame(b"old") if with_previous else None, "{}", 0)
  settings = Settings(model="test/model", max_output_tokens=321)
  body = request_body(observation, settings, correction)
  content: list[dict[str, object]] = [{"type": "text", "text": "{}"}]
  if correction:
    content.append({"type": "text", "text": correction})
  if with_previous:
    content.extend(
      [
        {"type": "text", "text": "previous screenshot"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,b2xk"}},
      ]
    )
  content.extend(
    [
      {"type": "text", "text": "current screenshot"},
      {"type": "image_url", "image_url": {"url": "data:image/png;base64,cG5n"}},
    ]
  )
  assert body["messages"] == [
    {"role": "system", "content": SYSTEM_PROMPT},
    {"role": "user", "content": content},
  ]
  assert body["model"] == "test/model"
  assert body["max_tokens"] == 321
  assert body["stream"] is False
  assert body["provider"] == {"require_parameters": True}
  response_format = body["response_format"]
  assert isinstance(response_format, dict)
  assert response_format["type"] == "json_schema"
  schema_options = response_format["json_schema"]
  assert schema_options["strict"] is True
  schema = schema_options["schema"]
  assert schema["additionalProperties"] is False
  assert set(schema["required"]) == {
    "kind",
    "action",
    "message",
    "expected",
    "notes",
    "previous_result",
  }
  assert schema["properties"]["kind"]["enum"] == ["act", "done", "help"]
  assert schema["$defs"]["Click"]["properties"]["x"]["minimum"] == 0
  assert schema["$defs"]["Click"]["properties"]["x"]["maximum"] == 1


def test_images_schema_and_retry() -> None:
  from fsd.operator.client import OpenRouterClient

  async def scenario() -> None:
    bodies: list[dict[str, object]] = []

    async def handle(request: httpx.Request) -> httpx.Response:
      assert request.method == "POST"
      assert str(request.url) == Settings().api_url
      assert request.headers["Authorization"] == "Bearer test-key"
      bodies.append(json.loads(request.content))
      if len(bodies) == 1:
        return httpx.Response(503)
      return httpx.Response(200, json=response_body(done_content()))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
      client = OpenRouterClient(http, "test-key", Settings())
      result = await client.decide(Observation(frame(b"png"), None, "{}", 0), Control())
    assert len(bodies) == 2
    assert bodies[0] == bodies[1]
    assert result.decision.kind == "done"
    assert result.input_tokens == 100
    assert result.output_tokens == 30
    assert result.cost == 0.001
    body = bodies[-1]
    assert body["model"] == Settings().model
    assert "data:image/png;base64,cG5n" in json.dumps(body["messages"])
    response_format = body["response_format"]
    assert isinstance(response_format, dict)
    assert response_format["json_schema"]["strict"] is True
    assert "test-key" not in json.dumps(body)

  asyncio.run(scenario())


def test_invalid_content_is_not_a_transport_retry() -> None:
  from fsd.operator.client import InvalidDecision, OpenRouterClient

  async def scenario() -> None:
    requests = 0

    async def handle(request: httpx.Request) -> httpx.Response:
      nonlocal requests
      requests += 1
      return httpx.Response(200, json=response_body("not json"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
      with pytest.raises(InvalidDecision):
        await OpenRouterClient(http, "key", Settings()).decide(
          Observation(frame(b"png"), None, "{}", 0),
          Control(),
        )
    assert requests == 1

  asyncio.run(scenario())


@pytest.mark.parametrize("status", [400, 401, 402, 403])
def test_permanent_http_errors_are_not_retried(status: int) -> None:
  from fsd.operator.client import InferenceError, OpenRouterClient

  async def scenario() -> None:
    requests = 0

    async def handle(request: httpx.Request) -> httpx.Response:
      nonlocal requests
      requests += 1
      return httpx.Response(status, text="private-body")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
      with pytest.raises(InferenceError) as error:
        await OpenRouterClient(http, "private-key", Settings()).decide(
          Observation(frame(b"png"), None, "{}", 0),
          Control(),
        )
    assert requests == 1
    assert str(error.value)
    assert "private-body" not in str(error.value)
    assert "private-key" not in str(error.value)

  asyncio.run(scenario())


@pytest.mark.parametrize("failure", [429, 503, "connection", "timeout"])
def test_transient_failures_exhaust_bounded_retries(failure: int | str) -> None:
  from fsd.operator.client import InferenceError, OpenRouterClient

  async def scenario() -> None:
    requests = 0

    async def handle(request: httpx.Request) -> httpx.Response:
      nonlocal requests
      requests += 1
      if failure == "connection":
        raise httpx.ConnectError("private-body private-key", request=request)
      if failure == "timeout":
        raise httpx.ReadTimeout("private-body private-key", request=request)
      assert isinstance(failure, int)
      return httpx.Response(failure, text="private-body")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
      with pytest.raises(InferenceError) as error:
        await OpenRouterClient(http, "private-key", Settings(retries=1)).decide(
          Observation(frame(b"png"), None, "{}", 0),
          Control(),
        )
    assert requests == 2
    assert "private-body" not in str(error.value)
    assert "private-key" not in str(error.value)
    assert error.value.__cause__ is None

  asyncio.run(scenario())


@pytest.mark.parametrize(
  ("finish_reason", "content"),
  [
    ("length", done_content()),
    ("stop", None),
    (
      "stop",
      json.dumps(
        {
          "kind": "act",
          "action": None,
          "message": "private-text",
          "expected": "Done",
          "notes": "",
          "previous_result": "none",
        }
      ),
    ),
  ],
)
def test_incomplete_or_inconsistent_decisions_are_rejected_without_retry(
  finish_reason: str, content: str | None
) -> None:
  from fsd.operator.client import InvalidDecision, OpenRouterClient

  async def scenario() -> None:
    requests = 0

    async def handle(request: httpx.Request) -> httpx.Response:
      nonlocal requests
      requests += 1
      return httpx.Response(
        200,
        json={
          "choices": [{"finish_reason": finish_reason, "message": {"content": content}}],
        },
      )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
      with pytest.raises(InvalidDecision) as error:
        await OpenRouterClient(http, "key", Settings()).decide(
          Observation(frame(b"png"), None, "{}", 0),
          Control(),
        )
    assert requests == 1
    assert "private-text" not in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__suppress_context__

  asyncio.run(scenario())


def test_higher_retry_budget_reaches_final_attempt() -> None:
  from fsd.operator.client import OpenRouterClient

  async def scenario() -> None:
    requests = 0

    async def handle(request: httpx.Request) -> httpx.Response:
      nonlocal requests
      requests += 1
      if requests < 5:
        return httpx.Response(503)
      return httpx.Response(200, json=response_body(done_content()))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
      result = await OpenRouterClient(http, "key", Settings(retries=4)).decide(
        Observation(frame(b"png"), None, "{}", 0),
        Control(),
      )
    assert requests == 5
    assert result.decision.kind == "done"

  asyncio.run(scenario())


def test_missing_usage_remains_unknown_cost() -> None:
  from fsd.operator.client import OpenRouterClient

  async def scenario() -> None:
    async def handle(request: httpx.Request) -> httpx.Response:
      body = response_body(done_content())
      body.pop("usage")
      return httpx.Response(200, json=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
      result = await OpenRouterClient(http, "key", Settings()).decide(
        Observation(frame(b"png"), None, "{}", 0),
        Control(),
      )
    assert result.cost is None
    assert result.input_tokens == 0
    assert result.output_tokens == 0

  asyncio.run(scenario())


def test_cancelled_run_never_sends_a_request() -> None:
  from fsd.operator.client import OpenRouterClient
  from fsd.operator.control import RunCancelled

  async def scenario() -> None:
    requests = 0
    control = Control()
    control.cancel()

    async def handle(request: httpx.Request) -> httpx.Response:
      nonlocal requests
      requests += 1
      return httpx.Response(200, json=response_body(done_content()))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
      with pytest.raises(RunCancelled):
        await OpenRouterClient(http, "key", Settings()).decide(
          Observation(frame(b"png"), None, "{}", 0),
          control,
        )
    assert requests == 0

  asyncio.run(scenario())


def test_cancellation_interrupts_request_and_discards_late_response() -> None:
  from fsd.operator.client import OpenRouterClient
  from fsd.operator.control import RunCancelled

  async def scenario() -> None:
    entered = asyncio.Event()
    finished = asyncio.Event()
    control = Control()
    requests = 0

    async def handle(request: httpx.Request) -> httpx.Response:
      nonlocal requests
      requests += 1
      entered.set()
      try:
        await asyncio.Event().wait()
      except asyncio.CancelledError:
        return httpx.Response(200, json=response_body(done_content()))
      finally:
        finished.set()
      raise AssertionError("The pending request must be cancelled")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
      task = asyncio.create_task(
        OpenRouterClient(http, "key", Settings()).decide(
          Observation(frame(b"png"), None, "{}", 0),
          control,
        )
      )
      try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        control.cancel()
        with pytest.raises(RunCancelled):
          await asyncio.wait_for(task, timeout=1)
        await asyncio.wait_for(finished.wait(), timeout=1)
      finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert requests == 1

  asyncio.run(scenario())


def test_request_deadline_interrupts_transport() -> None:
  from fsd.operator.client import InferenceError, OpenRouterClient

  async def scenario() -> None:
    finished = asyncio.Event()
    requests = 0

    async def handle(request: httpx.Request) -> httpx.Response:
      nonlocal requests
      requests += 1
      try:
        await asyncio.Event().wait()
      finally:
        finished.set()
      raise AssertionError("The pending request must time out")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
      client = OpenRouterClient(http, "key", Settings(request_seconds=0.02, retries=0))
      with pytest.raises(InferenceError):
        await asyncio.wait_for(
          client.decide(
            Observation(frame(b"png"), None, "{}", 0),
            Control(),
          ),
          timeout=1,
        )
      await asyncio.wait_for(finished.wait(), timeout=1)
    assert requests == 1

  asyncio.run(scenario())


def test_cancellation_interrupts_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
  from types import SimpleNamespace

  from fsd.operator import client as client_module
  from fsd.operator.control import RunCancelled

  async def scenario() -> None:
    entered = asyncio.Event()
    finished = asyncio.Event()
    requests = 0
    control = Control()

    async def observed_sleep(delay: float) -> None:
      entered.set()
      try:
        await asyncio.sleep(delay)
      finally:
        finished.set()

    monkeypatch.setattr(client_module, "asyncio", SimpleNamespace(sleep=observed_sleep))

    async def handle(request: httpx.Request) -> httpx.Response:
      nonlocal requests
      requests += 1
      return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
      task = asyncio.create_task(
        client_module.OpenRouterClient(http, "key", Settings()).decide(
          Observation(frame(b"png"), None, "{}", 0),
          control,
        )
      )
      try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        control.cancel()
        with pytest.raises(RunCancelled):
          await asyncio.wait_for(task, timeout=1)
        await asyncio.wait_for(finished.wait(), timeout=1)
      finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert requests == 1

  asyncio.run(scenario())


def ask(content: str | None, finish: str = "stop") -> httpx.Response:
  return httpx.Response(
    200,
    json={
      "choices": [{"finish_reason": finish, "message": {"content": content}}],
      "usage": {"prompt_tokens": 100, "completion_tokens": 30, "cost": 0.001},
    },
  )


@pytest.mark.parametrize(
  ("response", "cause"),
  [
    (httpx.Response(200, content=b"not json"), "envelope"),
    (httpx.Response(200, json={"choices": []}), "envelope"),
    (ask(done_content(), finish="length"), "finish_reason"),
    (ask(None), "empty"),
    (ask("{}"), "schema"),
  ],
)
def test_invalid_responses_report_their_cause(response: httpx.Response, cause: str) -> None:
  # The trace needs the cause to tell truncation from schema drift.
  from fsd.operator.client import InvalidDecision, OpenRouterClient

  async def scenario() -> None:
    async def handle(request: httpx.Request) -> httpx.Response:
      return response

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
      with pytest.raises(InvalidDecision) as invalid:
        await OpenRouterClient(http, "key", Settings()).decide(
          Observation(frame(b"png"), None, "{}", 0), Control()
        )
    assert invalid.value.cause == cause
    assert invalid.value.__suppress_context__

  asyncio.run(scenario())


def test_encoding_is_timed_separately_from_the_request(monkeypatch: pytest.MonkeyPatch) -> None:
  # The research asked for this split; request time must not include encoding.
  from fsd.operator.client import OpenRouterClient

  now = 0.0
  monkeypatch.setattr(client_module, "time", SimpleNamespace(monotonic=lambda: now))
  original = client_module.request_body

  def slow_body(*args: object) -> dict[str, object]:
    nonlocal now
    now += 2.0
    return original(*args)  # type: ignore[arg-type]

  monkeypatch.setattr(client_module, "request_body", slow_body)

  async def scenario() -> None:
    async def handle(request: httpx.Request) -> httpx.Response:
      nonlocal now
      now += 3.0
      return ask(done_content())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
      result = await OpenRouterClient(http, "key", Settings()).decide(
        Observation(frame(b"png"), None, "{}", 0), Control()
      )
    assert result.encode_seconds == 2.0
    assert result.request_seconds == 3.0

  asyncio.run(scenario())


@pytest.mark.parametrize(("details", "expected"), [({"cached_tokens": 40}, 40), (None, None)])
def test_cached_tokens_are_recorded_or_left_unknown(
  details: dict[str, int] | None, expected: int | None
) -> None:
  # Unknown is not zero: no cost claim may assume a cache hit or miss.
  from fsd.operator.client import OpenRouterClient

  usage: dict[str, object] = {"prompt_tokens": 100, "completion_tokens": 30}
  if details is not None:
    usage["prompt_tokens_details"] = details

  async def scenario() -> None:
    async def handle(request: httpx.Request) -> httpx.Response:
      return httpx.Response(
        200,
        json={
          "choices": [{"finish_reason": "stop", "message": {"content": done_content()}}],
          "usage": usage,
        },
      )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
      result = await OpenRouterClient(http, "key", Settings()).decide(
        Observation(frame(b"png"), None, "{}", 0), Control()
      )
    assert result.cached_input_tokens == expected

  asyncio.run(scenario())


@pytest.mark.parametrize("correction", ["", "Return a valid completion verdict."])
def test_verify_body_limits_context_and_requires_verdict_schema(correction: str) -> None:
  from fsd.operator.client import VERIFY_PROMPT, verify_body

  goal = 'Save "draft"\nand close the dialog'
  settings = Settings(model="test/verifier", max_output_tokens=123)
  body = verify_body(goal, frame(b"png"), settings, correction)
  content: list[dict[str, object]] = [{"type": "text", "text": json.dumps({"goal": goal})}]
  if correction:
    content.append({"type": "text", "text": correction})
  content.extend(
    [
      {"type": "text", "text": "current screenshot"},
      {"type": "image_url", "image_url": {"url": "data:image/png;base64,cG5n"}},
    ]
  )

  assert body["messages"] == [
    {"role": "system", "content": VERIFY_PROMPT},
    {"role": "user", "content": content},
  ]
  assert body["model"] == "test/verifier"
  assert body["max_tokens"] == 123
  assert body["stream"] is False
  assert body["provider"] == {"require_parameters": True}
  response_format = body["response_format"]
  assert isinstance(response_format, dict)
  assert response_format["type"] == "json_schema"
  options = response_format["json_schema"]
  assert options["name"] == "completion_verdict"
  assert options["strict"] is True
  schema = options["schema"]
  assert schema["additionalProperties"] is False
  assert set(schema["properties"]) == {"complete", "evidence"}
  assert set(schema["required"]) == {"complete", "evidence"}


def test_verification_sees_only_the_goal_and_one_frame() -> None:
  # Isolation is the point: history and notes carry the reasoning behind the claim.
  from fsd.operator.client import VERIFY_PROMPT, OpenRouterClient

  bodies: list[dict[str, object]] = []

  async def scenario() -> None:
    async def handle(request: httpx.Request) -> httpx.Response:
      bodies.append(json.loads(request.content))
      return ask(json.dumps({"complete": False, "evidence": "The file is still unsaved."}))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
      result = await OpenRouterClient(http, "key", Settings()).verify(
        "Save the document", frame(b"png"), Control()
      )
    assert result.verdict.complete is False
    assert result.verdict.evidence == "The file is still unsaved."

  asyncio.run(scenario())
  messages = bodies[0]["messages"]
  assert isinstance(messages, list)
  assert messages[0] == {"role": "system", "content": VERIFY_PROMPT}
  content = messages[1]["content"]
  assert [part["type"] for part in content].count("image_url") == 1
  text = json.dumps(content)
  assert "Save the document" in text
  assert "history" not in text and "notes" not in text and "previous" not in text
  response_format = bodies[0]["response_format"]
  assert isinstance(response_format, dict)
  assert response_format["json_schema"]["name"] == "completion_verdict"


def test_invalid_verdict_reports_schema_cause() -> None:
  from fsd.operator.client import InvalidDecision, OpenRouterClient

  async def scenario() -> None:
    async def handle(request: httpx.Request) -> httpx.Response:
      return ask(json.dumps({"complete": True, "evidence": ""}))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
      with pytest.raises(InvalidDecision) as invalid:
        await OpenRouterClient(http, "key", Settings()).verify("Goal", frame(b"png"), Control())
    assert invalid.value.cause == "schema"

  asyncio.run(scenario())
