from collections.abc import Awaitable, Callable

from fsd.approval.gate import ActionGate
from fsd.approval.store import ApprovalStore
from fsd.operator.client import DecisionClient
from fsd.operator.config import Settings
from fsd.operator.contracts import Event, Reply
from fsd.platform.base import Platform

EventSink = Callable[[Event], Awaitable[Reply | None]]


class RunLimit(Exception):
  pass


class Engine:
  def __init__(
    self,
    platform: Platform,
    store: ApprovalStore,
    client: DecisionClient,
    settings: Settings,
  ) -> None:
    self.platform = platform
    self.store = store
    self.client = client
    self.settings = settings
    self.gate = ActionGate(platform, store)
    self._active: object | None = None
    self.input_uncertain = False
