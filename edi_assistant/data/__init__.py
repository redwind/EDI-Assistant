"""WP-A data layer public facade."""
from .excel_reader import list_sheets, load_grid
from .excel_writeback import write_back, writeback_path_for
from .factories import FactoryStore
from .header_detect import detect_header
from .mapping import apply_template_to_detection, suggest_mapping, validate_mapping
from .planner import PlanOptions, build_plan, plan_summary_rows
from .results import ResultsWriter
from .rows import extract_rows
from .templates import Template, TemplateStore

__all__ = [
    "load_grid", "list_sheets", "detect_header", "suggest_mapping", "apply_template_to_detection",
    "validate_mapping", "extract_rows", "TemplateStore", "Template", "FactoryStore", "build_plan",
    "PlanOptions", "plan_summary_rows", "ResultsWriter", "write_back", "writeback_path_for",
]
