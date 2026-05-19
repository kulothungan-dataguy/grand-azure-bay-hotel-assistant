# tests/test_unit.py — pure unit tests, no LLM or network calls required
from datetime import date, timedelta


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def test_cache_key_normalises_whitespace():
    from app.cache.store import make_cache_key
    assert make_cache_key("check-in time") == make_cache_key("  check-in  time  ")


def test_cache_key_normalises_case():
    from app.cache.store import make_cache_key
    assert make_cache_key("Check-In Time") == make_cache_key("check-in time")


def test_cache_key_normalises_punctuation():
    from app.cache.store import make_cache_key
    # Trailing punctuation stripped — same underlying question
    assert make_cache_key("What is the check-in time?") == make_cache_key("what is the check-in time")


def test_cache_key_different_questions_differ():
    from app.cache.store import make_cache_key
    assert make_cache_key("check-in time") != make_cache_key("check-out time")


def test_is_cacheable_good_response():
    from app.cache.store import is_cacheable
    assert is_cacheable("Check-in is at 2:00 PM and check-out is at 11:00 AM.") is True


def test_is_cacheable_blocks_dont_have_info():
    from app.cache.store import is_cacheable
    assert is_cacheable("I don't have that information — please contact our front desk.") is False


def test_is_cacheable_blocks_contact_front_desk():
    from app.cache.store import is_cacheable
    assert is_cacheable("Please contact our front desk for more details.") is False


def test_is_cacheable_blocks_could_not_find():
    from app.cache.store import is_cacheable
    assert is_cacheable("I could not find that information in our records.") is False


def test_is_cacheable_partial_match_blocked():
    from app.cache.store import is_cacheable
    # Fallback phrase embedded in a longer sentence should still block
    assert is_cacheable("Unfortunately, I don't have that information available right now.") is False


# ---------------------------------------------------------------------------
# Active reservation filter
# ---------------------------------------------------------------------------

def test_is_active_confirmed_future():
    from app.tools.reservation_tools import _is_active
    future = (date.today() + timedelta(days=30)).isoformat()
    r = {"status": "CONFIRMED", "check_out_date": future}
    assert _is_active(r) is True


def test_is_active_confirmed_today():
    from app.tools.reservation_tools import _is_active
    today = date.today().isoformat()
    r = {"status": "CONFIRMED", "check_out_date": today}
    assert _is_active(r) is True   # checks today are still active


def test_is_active_confirmed_past():
    from app.tools.reservation_tools import _is_active
    past = (date.today() - timedelta(days=1)).isoformat()
    r = {"status": "CONFIRMED", "check_out_date": past}
    assert _is_active(r) is False


def test_is_active_cancelled_future():
    from app.tools.reservation_tools import _is_active
    future = (date.today() + timedelta(days=10)).isoformat()
    r = {"status": "CANCELLED", "check_out_date": future}
    assert _is_active(r) is False


def test_is_active_bad_date_returns_false():
    from app.tools.reservation_tools import _is_active
    r = {"status": "CONFIRMED", "check_out_date": "not-a-date"}
    assert _is_active(r) is False


def test_is_active_missing_fields_returns_false():
    from app.tools.reservation_tools import _is_active
    assert _is_active({}) is False


# ---------------------------------------------------------------------------
# History window helper
# ---------------------------------------------------------------------------

def test_append_assistant_reply_stores_both_roles():
    from app.api.server import _append_assistant_reply
    memory = {"chat_history": [{"role": "user", "content": "Hi"}]}
    _append_assistant_reply(memory, "Hello!")
    roles = [m["role"] for m in memory["chat_history"]]
    assert roles == ["user", "assistant"]


def test_append_assistant_reply_trims_to_window():
    from app.api.server import _append_assistant_reply, _HISTORY_WINDOW
    memory = {"chat_history": []}
    for i in range(10):
        memory["chat_history"].append({"role": "user", "content": f"msg {i}"})
        _append_assistant_reply(memory, f"reply {i}")
    assert len(memory["chat_history"]) <= _HISTORY_WINDOW


def test_append_assistant_reply_keeps_most_recent():
    from app.api.server import _append_assistant_reply, _HISTORY_WINDOW
    memory = {"chat_history": []}
    for i in range(5):
        memory["chat_history"].append({"role": "user", "content": f"msg {i}"})
        _append_assistant_reply(memory, f"reply {i}")
    # Last message should be the most recent assistant reply
    assert memory["chat_history"][-1]["content"] == "reply 4"
