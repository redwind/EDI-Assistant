"""Error taxonomy."""
from __future__ import annotations


class EdiAssistantError(Exception):
    code: str = "generic"

    def __init__(self, message: str, *, message_vi: str = "", **ctx):
        super().__init__(message)
        self.message = message
        self.message_vi = message_vi or message
        self.ctx = ctx


# Data (WP-A raises)
class ExcelReadError(EdiAssistantError): code = "excel_read"
class HeaderNotFoundError(EdiAssistantError): code = "header_not_found"
class MappingIncompleteError(EdiAssistantError): code = "mapping_incomplete"   # ctx: missing=list[str]
class RowParseError(EdiAssistantError): code = "row_parse"                     # ctx: row, field, raw
class PlanError(EdiAssistantError): code = "plan"
class ConfigError(EdiAssistantError): code = "config"


# Automation (WP-B raises)
class BrowserLaunchError(EdiAssistantError): code = "browser_launch"
class NavigationError(EdiAssistantError): code = "navigation"
class ElementNotFoundError(EdiAssistantError): code = "element_not_found"     # ctx: key, tried
class PostconditionFailed(EdiAssistantError): code = "postcondition"          # ctx: step_id
class DataMismatchError(EdiAssistantError): code = "data_mismatch"
class ForbiddenActionError(EdiAssistantError): code = "forbidden_action"
class SessionExpiredError(EdiAssistantError): code = "session_expired"
class SiteBlockedError(EdiAssistantError): code = "site_blocked"             # ctx: reason; stops the run, never auto-retried
class UserAbortError(EdiAssistantError): code = "user_abort"
class StepSkipped(EdiAssistantError): code = "step_skipped"                   # control flow


# AI (WP-C raises, WP-B catches)
class AiError(EdiAssistantError): code = "ai"                                 # ctx: provider, status
class AiBudgetExceeded(EdiAssistantError): code = "ai_budget"
