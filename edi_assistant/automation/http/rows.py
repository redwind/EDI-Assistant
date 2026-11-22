"""Table rows of a page: each row's own cell texts, form controls and links.

Content of a nested table belongs to the nested row only, so an outer layout row never "contains" a data row's
controls (the bug that once ticked the wrong PO). A data row may still hold a nested table of its own
(Search Items puts the SKU sub-table inside the item row)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser


@dataclass
class Row:
    cells: list[str] = field(default_factory=list)
    controls: list[dict[str, str]] = field(default_factory=list)   # attrs of input/select inside the row
    links: list[str] = field(default_factory=list)                 # link texts
    has_child: bool = False

    @property
    def text(self) -> str:
        return " ".join(c for c in self.cells if c)

    def control_names(self, pattern: str) -> list[str]:
        rx = re.compile(pattern)
        return [c.get("name", "") for c in self.controls if rx.fullmatch(c.get("name", ""))]

    def has_cell(self, text: str) -> bool:
        return any(c == text for c in self.cells) or any(t == text for t in self.links)


class _RowParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[Row] = []
        self._stack: list[Row] = []
        self._link: list[str] | None = None
        self._skip = 0   # inside <script>/<style>

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag in ("script", "style"):
            self._skip += 1
        elif tag == "tr":
            if self._stack:
                self._stack[-1].has_child = True
            self._stack.append(Row())
        elif tag in ("td", "th") and self._stack:
            self._stack[-1].cells.append("")
        elif tag in ("input", "select", "textarea") and self._stack:
            self._stack[-1].controls.append(a)
        elif tag == "a":
            self._link = []

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag == "tr" and self._stack:
            row = self._stack.pop()
            row.cells = [" ".join(c.split()) for c in row.cells]
            row.links = [" ".join(t.split()) for t in row.links]
            self.rows.append(row)
        elif tag == "a" and self._link is not None:
            if self._stack:
                self._stack[-1].links.append("".join(self._link))
            self._link = None
        elif tag in ("table",):
            # a table closing implicitly closes rows still open inside it
            pass

    def handle_data(self, data):
        if self._skip:
            return
        if self._link is not None:
            self._link.append(data)
        if self._stack and self._stack[-1].cells:
            self._stack[-1].cells[-1] += data


def table_rows(html: str) -> list[Row]:
    p = _RowParser()
    p.feed(html)
    p.close()
    while p._stack:   # unclosed rows at end of document
        p.rows.append(p._stack.pop())
    return p.rows


_ERR = [re.compile(r'<font[^>]*color\s*=\s*["\']?red["\']?[^>]*>(.*?)</font>', re.S | re.I),
        re.compile(r'<[^>]*(?:id|class)\s*=\s*["\']?(?:errorbox|error|errors|errorMessage)["\']?[^>]*>(.*?)</', re.S | re.I)]


def page_errors(html: str) -> list[str]:
    """Visible red/error texts that carry words (asterisk markers ignored)."""
    out = []
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html or "", flags=re.S | re.I)
    for rx in _ERR:
        for m in rx.finditer(body):
            t = " ".join(re.sub(r"<[^>]+>", " ", m.group(1)).split())
            if re.search(r"[A-Za-z]{3,}", t):
                out.append(t)
    return out
