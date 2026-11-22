"""Automatic EDI login with the login kept in the OS credential store (core/credentials.py).

The only place the tool ever types a password, and only when all of this holds:
  * the page is on the configured EDI host and shows a password box inside a form (the login page),
  * the box is a password input inside the same form as the user box,
  * a login was saved by the user, and the previous automatic attempt of this browser session did not fail.
One attempt only: a wrong password / captcha / extra verification is left to the user (no lock-out loops)."""
from __future__ import annotations

import logging
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError

from edi_assistant.core import credentials

log = logging.getLogger("edi_assistant.autologin")

NAV_MS = 60_000

DONE, NO_LOGIN, FAILED, NOT_HERE = "done", "no_login", "failed", "not_here"


def _on_edi_login_page(session) -> tuple[bool, str]:
    """(True, '') on the login page of the configured EDI host, else (False, why)."""
    try:
        url = session.page.url
        page_host = (urlsplit(url).hostname or "").lower()
        site_host = (urlsplit(session.site.effective_base_url()).hostname or "").lower()
    except Exception as ex:  # noqa: BLE001
        return False, f"cannot read the page address ({type(ex).__name__})"
    if not site_host or page_host != site_host:
        return False, f"page host {page_host!r} is not the EDI host {site_host!r}"
    try:
        n = session.page.locator("input[type='password']").count()
    except Exception:  # noqa: BLE001
        n = 0
    if n != 1:
        return False, f"{n} password boxes on the page (expected exactly 1)"
    return True, ""


# The EDI login page is malformed HTML: in the DOM its inputs sit outside the <form> element, so CSS like
# "form input" finds nothing. The browser still knows each input's form owner (el.form): use that.
_FORM_FIELDS_JS = """() => {
  const pwd = document.querySelector("input[type='password']");
  if (!pwd || !pwd.form) return null;
  const f = pwd.form;
  const els = Array.from(f.elements);
  const user = els.find(e => e.name === 'User_ID') || els.find(e => e.tagName === 'INPUT' && ['text','email'].includes(e.type));
  const submit = els.find(e => (e.tagName === 'INPUT' || e.tagName === 'BUTTON') && e.type === 'submit');
  if (!user || !submit) return null;
  const tag = (e, k) => { e.setAttribute('data-edi-login', k); return k; };
  tag(pwd, 'pwd'); tag(user, 'user'); tag(submit, 'submit');
  return true;
}"""


def try_auto_login(session) -> str:
    """Fill and submit the EDI login form. Returns DONE / NO_LOGIN / FAILED / NOT_HERE."""
    if getattr(session, "auto_login_failed", False):
        log.info("automatic login skipped: it already failed in this browser session")
        return FAILED
    ok, why = _on_edi_login_page(session)
    if not ok:
        log.info("automatic login not attempted: %s", why)
        return NOT_HERE
    creds = credentials.load()
    if creds is None:
        log.info("automatic login not attempted: no saved login (%s)", credentials.backend_name() or "no store")
        return NO_LOGIN
    page = session.page
    try:
        if not page.evaluate(_FORM_FIELDS_JS):
            log.info("automatic login not attempted: login form incomplete")
            return NOT_HERE
        pwd = page.locator("[data-edi-login='pwd']")
        user = page.locator("[data-edi-login='user']")
        submit = page.locator("[data-edi-login='submit']")
        user.fill(creds.user)
        pwd.fill(creds.password)   # the one sanctioned password entry (see module docstring)
        try:
            with page.expect_navigation(wait_until="domcontentloaded", timeout=NAV_MS):
                submit.click()
        except PlaywrightError:
            pass
    except PlaywrightError as ex:
        log.warning("automatic login could not fill the form: %s", type(ex).__name__)
        session.auto_login_failed = True
        return FAILED
    if session.is_login_page():
        session.auto_login_failed = True   # wrong password / captcha / 2FA: hand over, never retry blindly
        log.warning("automatic login did not get past the login page")
        return FAILED
    log.info("logged in automatically as %s", creds.user)
    return DONE
