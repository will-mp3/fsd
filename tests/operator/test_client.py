import asyncio
import json

import httpx
import pytest

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
      content = json.dumps(
        {
          "kind": "done",
          "action": None,
          "message": "Complete",
          "expected": "",
          "notes": "",
          "previous_result": "success",
        }
      )
      return httpx.Response(200, json=response_body(content))

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
