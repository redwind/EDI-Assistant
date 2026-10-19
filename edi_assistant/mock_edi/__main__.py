"""`python -m edi_assistant.mock_edi --port 8765 [--no-login] [--dates-in-pdf] [--seed-excel PATH]`"""
from __future__ import annotations

import argparse
import re
import time

from .server import MockOptions, MockServer
from .state import MockState


def _seed_from_excel(state: MockState, path: str) -> None:
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True)
    masters: list[str] = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            for v in row:
                if v is None:
                    continue
                s = str(v).strip()
                if s.endswith(".0"):
                    s = s[:-2]
                for m in re.findall(r"(?<!\d)(\d{7}|\d{9})(?!\d)", s):
                    master = m[:7]
                    if master not in masters:
                        masters.append(master)
    for master in masters:
        for line in (1, 2):
            po = f"{master}{line:02d}"
            if po not in state.orders:
                state.add_order(po)


def main() -> None:
    ap = argparse.ArgumentParser(prog="edi_assistant.mock_edi")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-login", action="store_true")
    ap.add_argument("--dates-in-pdf", action="store_true")
    ap.add_argument("--seed-tracker", action="store_true")
    ap.add_argument("--seed-excel", default="")
    a = ap.parse_args()
    state = MockState()
    state.seed_default()
    if a.seed_excel:
        _seed_from_excel(state, a.seed_excel)
    srv = MockServer(MockOptions(port=a.port, require_login=not a.no_login, dates_in_pdf=a.dates_in_pdf,
                                  seed_tracker=a.seed_tracker), state)
    print(srv.start(), flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        srv.stop()


if __name__ == "__main__":
    main()
