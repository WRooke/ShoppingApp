"""Edge and error paths of the AnyList connector that the matrix/fault suites don't reach
(Chunk 6.7 branch-coverage pass — every remaining branch on the push path is either tested here or
was unreachable and removed). docs/anylist-push.md > Test map."""

from __future__ import annotations

import httpx
import pytest

from app.services import anylist_client as ac
from app.services.anylist_client import (
    AnyListError,
    PushItem,
    _decide,
    _PlannedOp,
    _resolve_existing,
    _verify_against,
)
from app.services.anylist_wire import AnyListItem
from tests.services.anylist_fake_server import FakeAnyListServer


@pytest.fixture(autouse=True)
def _reset():
    ac.reset_client()
    yield
    ac.reset_client()


# --- the decision function, directly -------------------------------------------------------


def test_decide_with_an_id_that_is_not_on_the_list_adds():
    d = _decide(PushItem(name="Milk", quantity="1 L", existing_id="gone"), {})
    assert d.kind == "add" and "no longer on the list" in d.reason


def test_resolve_existing_falls_back_to_an_exact_name_match_preferring_active():
    before = {
        "old": AnyListItem("old", "milk", "1 L", True),
        "live": AnyListItem("live", "Milk ", "1 L", False),
        "other": AnyListItem("other", "milk chocolate", None, False),
    }
    assert _resolve_existing(PushItem(name="MILK", quantity=None), before).existing_id == "live"
    assert _resolve_existing(PushItem(name="Milk", quantity=None, existing_id="old"), before).existing_id == "old"
    assert _resolve_existing(PushItem(name="Bread", quantity=None, existing_id="gone"), before).existing_id is None


def test_a_quantity_differing_only_in_case_or_spacing_is_the_same_amount():
    before = {"a": AnyListItem("a", "Milk", "1 L", False)}
    assert _decide(PushItem(name="Milk", quantity="1  l", existing_id="a"), before).kind == "noop"


# --- the read-back check, directly ---------------------------------------------------------


def _op(**kw):
    base = dict(item=PushItem(name="Milk", quantity="1 L", key="k"), kind="add", intended="added", ident="x",
                expected_qty="1 L")
    base.update(kw)
    return _PlannedOp(**base)


def test_verify_flags_each_way_a_line_can_be_wrong():
    assert _verify_against([], [op := _op()]) == {id(op): "not on the list after sending"}
    crossed = [AnyListItem("x", "Milk", "1 L", True)]
    assert "crossed off" in _verify_against(crossed, [_op()]).popitem()[1]
    qty = [AnyListItem("x", "Milk", "2 L", False)]
    assert "quantity shows '2 L'" in _verify_against(qty, [_op()]).popitem()[1]
    note = [AnyListItem("x", "Milk", "1 L", False, "other")]
    assert "note shows" in _verify_against(note, [_op(expected_note="wanted", check_note=True)]).popitem()[1]
    name = [AnyListItem("x", "Whole Milk", "1 L", False)]
    assert "name shows" in _verify_against(name, [_op(check_name=True)]).popitem()[1]
    dup = [AnyListItem("x", "Milk", "1 L", False), AnyListItem("old", "Milk", "1 L", False)]
    assert "duplicate" in _verify_against(dup, [_op(old_ident="old")]).popitem()[1]
    gone_old = [AnyListItem("x", "Milk", "1 L", False), AnyListItem("old", "Milk", "1 L", True)]
    assert _verify_against(gone_old, [_op(old_ident="old")]) == {}  # crossed-off old is not a duplicate
    assert _verify_against([], [_op(not_sent=True)]) == {}  # not-sent lines are reported separately


# --- login / auth / decode errors ----------------------------------------------------------


def _client(monkeypatch, handler):
    monkeypatch.setattr(ac.settings, "anylist_fake_mode", False, raising=False)
    monkeypatch.setattr(ac.settings, "anylist_enabled", True, raising=False)
    monkeypatch.setattr(ac, "_RETRY_BACKOFF_S", 0.0, raising=False)
    c = ac._RealAnyList("user@example.com", "pw")
    c._http = httpx.Client(base_url=ac.BASE_URL, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(ac, "_instance", c, raising=False)
    return c


def test_unconfigured_credentials_are_refused():
    with pytest.raises(ac.AnyListAuthError):
        ac._RealAnyList("REPLACE_ME@example.com", "pw")
    with pytest.raises(ac.AnyListAuthError):
        ac._RealAnyList("", "")


def test_login_failures_are_auth_errors_and_check_auth_never_raises(monkeypatch):
    def unreachable(request):
        raise httpx.ConnectError("down")

    c = _client(monkeypatch, unreachable)
    with pytest.raises(ac.AnyListAuthError, match="could not reach"):
        c.login()
    assert ac.check_auth().ok is False

    c = _client(monkeypatch, lambda r: httpx.Response(403))
    with pytest.raises(ac.AnyListAuthError, match="rejected"):
        c.login()
    assert ac.check_auth().ok is False

    c = _client(monkeypatch, lambda r: httpx.Response(200, json={"nope": 1}))
    with pytest.raises(ac.AnyListAuthError, match="no access_token"):
        c.login()


def test_check_auth_ok_when_login_works_and_reports_disabled_without_raising(monkeypatch):
    _client(monkeypatch, lambda r: httpx.Response(200, json={"access_token": "t"}))
    assert ac.check_auth().ok is True
    ac.reset_client()
    monkeypatch.setattr(ac.settings, "anylist_enabled", False, raising=False)
    monkeypatch.setattr(ac.settings, "anylist_fake_mode", False, raising=False)
    st = ac.check_auth()
    assert st.ok is False and "disabled" in st.detail.lower()
    monkeypatch.setattr(ac.settings, "anylist_fake_mode", True, raising=False)
    ac.reset_client()
    assert ac.check_auth().ok is True  # fake mode


def test_get_client_builds_a_real_client_from_settings(monkeypatch):
    monkeypatch.setattr(ac.settings, "anylist_fake_mode", False, raising=False)
    monkeypatch.setattr(ac.settings, "anylist_enabled", True, raising=False)
    monkeypatch.setattr(ac.settings, "anylist_email", "user@example.com", raising=False)
    monkeypatch.setattr(ac.settings, "anylist_password", "pw", raising=False)
    assert isinstance(ac._get_client(), ac._RealAnyList)


def test_an_undecodable_list_response_is_an_anylist_error(monkeypatch):
    def handler(request):
        if request.url.path == "/auth/token":
            return httpx.Response(200, json={"access_token": "t"})
        return httpx.Response(200, content=b"\xff\xff\xff not protobuf")

    _client(monkeypatch, handler)
    with pytest.raises(AnyListError, match="could not parse"):
        ac.get_items("TestList")


def test_list_reads_are_retried_but_bad_credentials_are_not(monkeypatch):
    server = FakeAnyListServer()
    server.get_rule = lambda n: ("status", 500) if n <= 2 else None
    server.install(monkeypatch)
    assert ac.get_items("TestList") == []  # two failed reads, third succeeds
    assert server.gets == 3

    server = FakeAnyListServer()
    server.get_rule = lambda n: ("status", 500)
    server.install(monkeypatch)
    with pytest.raises(AnyListError):
        ac.get_items("TestList")
    assert server.gets == ac._READ_ATTEMPTS  # bounded

    calls = {"n": 0}

    def rejecting(request):
        calls["n"] += 1
        return httpx.Response(403)

    _client(monkeypatch, rejecting)
    with pytest.raises(ac.AnyListAuthError):
        ac.get_items("TestList")
    assert calls["n"] == 1  # no retry loop on a credentials failure


def test_a_second_401_after_reauthenticating_is_an_error(monkeypatch):
    def handler(request):
        if request.url.path == "/auth/token":
            return httpx.Response(200, json={"access_token": "t"})
        return httpx.Response(401)

    _client(monkeypatch, handler)
    with pytest.raises(AnyListError, match="401"):
        ac.get_items("TestList")


def test_empty_push_still_validates_the_list_and_confirms(monkeypatch):
    server = FakeAnyListServer()
    server.install(monkeypatch)
    res = ac.add_or_increment_items([], list_name="TestList")
    assert res.confirmed and res.items == [] and server.posts == []
    with pytest.raises(AnyListError, match="not found"):
        ac.add_or_increment_items([], list_name="NoSuchList")


def test_fake_client_models_the_same_decisions(monkeypatch):
    monkeypatch.setattr(ac.settings, "anylist_fake_mode", True, raising=False)
    monkeypatch.setattr(ac.settings, "anylist_target_list_name", "TestList", raising=False)
    ac.reset_client()
    seen = []
    res = ac.add_or_increment_items(
        [PushItem(name="Butter", quantity="250 g", note="soft", existing_id="seed-butter", key="a"),  # seeded crossed off
         PushItem(name="Milk", quantity="2L bottle", existing_id="seed-milk", key="b"),  # identical active
         PushItem(name="Eggs", quantity="2", existing_id="seed-eggs", key="c"),  # bare wanted quantity on a seeded "1 dozen": set-quantity in place
         PushItem(name="Bread", quantity="1", key="d")],
        on_item=lambda ref, st: seen.append((ref, st)), on_stage=lambda s: seen.append(s),
    )
    outcomes = {r.key: r.outcome for r in res.items}
    assert outcomes == {"a": "un-crossed", "b": "already-active", "c": "updated", "d": "added"}
    assert res.confirmed and seen[0] == "sending" and "confirming" in seen
    # the in-place update kept its id, so a repeat is a no-op (fake mirrors the real connector)
    res2 = ac.add_or_increment_items([PushItem(name="Eggs", quantity="2", existing_id="seed-eggs", key="c")])
    assert res2.items[0].outcome == "already-active"
