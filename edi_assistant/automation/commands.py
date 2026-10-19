"""Worker command dataclasses (GUI -> worker)."""
from __future__ import annotations

from dataclasses import dataclass, field

from edi_assistant.core.models import RunPlan


@dataclass(slots=True)
class Command:
    pass


@dataclass(slots=True)
class OpenBrowser(Command):
    navigate_home: bool = True


@dataclass(slots=True)
class CloseBrowser(Command):
    pass


@dataclass(slots=True)
class NavigateTo(Command):
    path: str = "gateway/inbox.do"


@dataclass(slots=True)
class RunPlanCommand(Command):
    plan: RunPlan | None = None


@dataclass(slots=True)
class Highlight(Command):
    key: str = ""
    vars: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class Pick(Command):
    key: str = ""


@dataclass(slots=True)
class CancelPick(Command):
    pass


@dataclass(slots=True)
class TestKey(Command):
    key: str = ""
    vars: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class OpenInspector(Command):
    pass


@dataclass(slots=True)
class ReloadSelectors(Command):
    pass


@dataclass(slots=True)
class Shutdown(Command):
    pass
