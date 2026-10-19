"""DialogPolicy: dismiss by default, accept only when armed and matching."""
from __future__ import annotations

import pytest


@pytest.fixture
def page(session):
    p = session.page
    p.set_content("<html><body>x</body></html>")
    return p


def test_unexpected_confirm_dismissed(session, page):
    assert page.evaluate("confirm('Are you sure?')") is False
    assert session.dialogs.pop_last() == ("confirm", "Are you sure?", False)


def test_armed_accept_once(session, page):
    session.dialogs.expect_accept(r"do you want to add the selected")
    assert page.evaluate("confirm('Do you want to add the selected Purchase Orders ?')") is True
    # disarmed after use
    assert page.evaluate("confirm('Do you want to add the selected Purchase Orders ?')") is False


def test_armed_but_other_message_dismissed(session, page):
    session.dialogs.expect_accept(r"do you want to add the selected")
    assert page.evaluate("confirm('Something else entirely')") is False


@pytest.mark.parametrize("msg", ["Submit this ASN?", "Do you want to cancel this shipment?", "Delete it", "Remove row?",
                                 "Transmit now"])
def test_forbidden_text_always_dismissed(session, page, msg):
    session.dialogs.expect_accept(r".*")   # even a catch-all arm must not accept these
    assert page.evaluate("m => confirm(m)", msg) is False


def test_alert_accepted_prompt_dismissed(session, page):
    page.evaluate("alert('hello')")
    assert session.dialogs.pop_last() == ("alert", "hello", True)
    assert page.evaluate("prompt('name?')") is None


def test_expectation_expires(session, page):
    session.dialogs.expect_accept(r"add", timeout_s=-1)
    assert page.evaluate("confirm('please add')") is False
