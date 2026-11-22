"""HTML forms as a browser would submit them.

The EDI pages are old JSP with forms opened inside tables, so a DOM view often shows the <form> empty while
its controls sit outside it. A browser still submits those controls (form-element pointer); parsing the
*source* order of <form> ... </form> tags reproduces exactly what the browser sends."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

_SKIP_TYPES = {"submit", "button", "image", "reset", "file"}


@dataclass
class Option:
    value: str
    text: str
    selected: bool
    attrs: dict[str, str]


@dataclass
class Control:
    tag: str                       # input | select | textarea | button
    name: str
    type: str = ""
    value: str = ""
    checked: bool = False
    disabled: bool = False
    multiple: bool = False
    options: list[Option] = field(default_factory=list)
    attrs: dict[str, str] = field(default_factory=dict)

    def selected_options(self) -> list[Option]:
        sel = [o for o in self.options if o.selected]
        if not sel and self.options and not self.multiple:
            return [self.options[0]]
        return sel if self.multiple else sel[-1:]


@dataclass
class Form:
    name: str
    action: str
    method: str
    attrs: dict[str, str]
    controls: list[Control] = field(default_factory=list)

    def control(self, name: str) -> Control | None:
        return next((c for c in self.controls if c.name == name), None)

    def names(self, pattern: str) -> list[str]:
        rx = re.compile(pattern)
        return [c.name for c in self.controls if rx.fullmatch(c.name)]

    def pairs(self, overrides: dict[str, str | None] | None = None,
              submitter: tuple[str, str] | None = None) -> list[tuple[str, str]]:
        """(name, value) pairs in document order, as the browser sends them.
        overrides: replace the value of an existing control (None drops it); unknown names are appended."""
        overrides = dict(overrides or {})
        out: list[tuple[str, str]] = []
        used: set[str] = set()
        for c in self.controls:
            if not c.name or c.disabled:
                continue
            vals: list[str]
            if c.tag == "select":
                vals = [o.value for o in c.selected_options()]
            elif c.tag in ("input", "button"):
                t = c.type
                if t in _SKIP_TYPES or c.tag == "button":
                    continue
                if t in ("checkbox", "radio"):
                    if not c.checked:
                        if c.name in overrides and overrides[c.name] is not None and c.name not in used:
                            pass   # an override ticks it (e.g. CB_123=on)
                        else:
                            continue
                    vals = [c.value or "on"]
                else:
                    vals = [c.value]
            else:   # textarea
                vals = [c.value]
            if c.name in overrides:
                if c.name in used:
                    continue          # the override replaces every control of that name once
                used.add(c.name)
                v = overrides[c.name]
                if v is None:
                    continue
                vals = [v]
            out.extend((c.name, v) for v in vals)
        for k, v in overrides.items():
            if k not in used and v is not None:
                out.append((k, v))
        if submitter is not None:   # the clicked button goes where it sits in the form
            pos = next((i for i, c in enumerate(self.controls)
                        if c.name == submitter[0] and c.type == "submit" and c.value == submitter[1]), None)
            if pos is None:
                out.append(submitter)
            else:
                before = {c.name for c in self.controls[:pos]}
                idx = next((i for i, (k, _) in enumerate(out) if k not in before), len(out))
                out.insert(idx, submitter)
        return out

    def option_value(self, name: str, *, value: str | None = None, label: str | None = None,
                     prefix: str | None = None) -> str | None:
        """Value of the option of select `name` matching value -> exact label -> label prefix (case-insensitive)."""
        c = self.control(name)
        if c is None or c.tag != "select":
            return None
        for o in c.options:
            if value is not None and o.value == value:
                return o.value
        for o in c.options:
            if label is not None and o.text.lower() == label.lower():
                return o.value
        for o in c.options:
            if prefix and o.text.lower().startswith(prefix.lower()):
                return o.value
        return None

    def option(self, name: str, value: str) -> Option | None:
        c = self.control(name)
        return next((o for o in c.options if o.value == value), None) if c is not None else None


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.forms: list[Form] = []
        self.loose: list[Control] = []          # controls outside any form
        self._form: Form | None = None
        self._select: Control | None = None
        self._option: Option | None = None
        self._textarea: Control | None = None

    def _add(self, c: Control) -> None:
        (self._form.controls if self._form is not None else self.loose).append(c)

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v if v is not None else "") for k, v in attrs}
        if tag == "form":
            self._form = Form(a.get("name", ""), a.get("action", ""), (a.get("method") or "get").lower(), a)
            self.forms.append(self._form)
        elif tag == "input":
            self._add(Control("input", a.get("name", ""), a.get("type", "text").lower(), a.get("value", ""),
                              "checked" in a, "disabled" in a, attrs=a))
        elif tag == "button":
            self._add(Control("button", a.get("name", ""), a.get("type", "submit").lower(), a.get("value", ""),
                              disabled="disabled" in a, attrs=a))
        elif tag == "select":
            self._select = Control("select", a.get("name", ""), disabled="disabled" in a, multiple="multiple" in a,
                                   attrs=a)
            self._add(self._select)
        elif tag == "option" and self._select is not None:
            self._close_option()
            self._option = Option(a.get("value"), "", "selected" in a, a)   # value None = use text
            self._select.options.append(self._option)
        elif tag == "textarea":
            self._textarea = Control("textarea", a.get("name", ""), disabled="disabled" in a, attrs=a)
            self._add(self._textarea)

    def _close_option(self):
        if self._option is not None:
            self._option.text = " ".join(self._option.text.split())
            if self._option.value is None:
                self._option.value = self._option.text
            self._option = None

    def handle_endtag(self, tag):
        if tag == "form":
            self._form = None
        elif tag == "select":
            self._close_option()
            self._select = None
        elif tag == "option":
            self._close_option()
        elif tag == "textarea":
            self._textarea = None

    def handle_data(self, data):
        if self._option is not None:
            self._option.text += data
        elif self._textarea is not None:
            self._textarea.value += data


def parse_forms(html: str) -> tuple[list[Form], list[Control]]:
    p = _Parser()
    p.feed(html)
    p.close()
    p._close_option()
    return p.forms, p.loose


def get_form(html: str, name: str | None = None, action_contains: str | None = None) -> Form:
    forms, _ = parse_forms(html)
    for f in forms:
        if (name is None or f.name == name) and (action_contains is None or action_contains in f.action):
            return f
    raise LookupError(f"form {name or action_contains!r} not on the page")


def title_of(html: str) -> str:
    m = re.search(r"<title>(.*?)</title>", html or "", re.S | re.I)
    return " ".join(m.group(1).split()) if m else ""
