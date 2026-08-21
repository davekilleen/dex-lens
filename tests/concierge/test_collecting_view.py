"""The in-progress page must not be a dead end.

It announced a read-only inspection in progress and then stopped, with no
indication that the person was the one who had to press a button to discover
it had finished seconds earlier. The obvious reading is that it hung, and it
sits at the exact moment a person has just granted read access to their own
files — the worst possible place to look stuck.
"""

from __future__ import annotations

import re

from capability_exchange.concierge.views import render_collecting

CSRF = "test-csrf-token"


def test_the_page_moves_on_by_itself() -> None:
    page = render_collecting(csrf_token=CSRF)

    match = re.search(
        r'<meta http-equiv="refresh" content="(\d+);url=(/[^"]*)"',
        page,
    )
    assert match, "the in-progress page must refresh itself, not wait to be poked"
    delay, target = int(match.group(1)), match.group(2)
    assert target == "/session"
    assert delay <= 5, f"a {delay}s wait still reads as a hang"


def test_stopping_stays_available_while_it_refreshes() -> None:
    """Auto-refresh must not cost the person the ability to stop the read."""
    page = render_collecting(csrf_token=CSRF)

    assert '<form method="post" action="/cancel">' in page
    assert CSRF in page


def test_the_page_needs_no_script() -> None:
    """The session CSP forbids script outright; keep it that way."""
    page = render_collecting(csrf_token=CSRF)

    assert "<script" not in page.lower()
