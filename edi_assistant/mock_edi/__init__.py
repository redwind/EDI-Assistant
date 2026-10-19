"""Local mock of the EDI Gateway portal (stdlib only)."""
from .server import MockOptions, MockServer
from .state import MockState

__all__ = ["MockOptions", "MockServer", "MockState"]
