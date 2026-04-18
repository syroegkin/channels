import os
import re

import pytest

from channels.hackernews import HackernewsChannel
from channels.base import ChannelsError

from .conftest import FakeSession, FakeResponse, load_fixture, fixture_path


FIXTURES = "hackernews"


@pytest.fixture
def channel():
    ch = HackernewsChannel()
    # Disable thread-pool parallelism in offline tests — FakeSession is
    # single-threaded and we want deterministic call ordering anyway.
    ch.parallel_fetches = 1
    return ch


@pytest.fixture
def client(channel):
    return channel.new_client("offline-test")


def _fixture_router(item_ids_served, list_body=None):
    """Build a routing handler that serves topstories.json and item/{id}.json
    from the fixture directory. Returns (routes_dict, missing_set).

    ``missing_set`` records any item IDs we asked for but didn't have fixture
    files for — tests can assert this to ensure they fully pre-recorded."""
    item_pattern = re.compile(r"/item/(\d+)\.json")
    missing = set()

    def handler(url, params=None, **kw):
        if url.endswith("topstories.json") or url.endswith("newstories.json") \
                or url.endswith("beststories.json") or url.endswith("askstories.json") \
                or url.endswith("showstories.json") or url.endswith("jobstories.json"):
            return FakeResponse(200, json_body=list_body or [])
        m = item_pattern.search(url)
        if m:
            iid = m.group(1)
            path = fixture_path(FIXTURES, "item_{0}.json".format(iid))
            if not os.path.isfile(path):
                missing.add(iid)
                return FakeResponse(200, json_body=None)
            return FakeResponse(200, json_body=load_fixture(FIXTURES, "item_{0}.json".format(iid)))
        raise AssertionError("unexpected URL: " + url)

    return {"hacker-news.firebaseio.com": handler}, missing


# ---------- boards ----------

def test_get_boards_returns_static_list(channel, client):
    boards = channel.get_boards(client, limit=0)
    ids = [b.id for b in boards]
    assert ids == ["top", "new", "best", "ask", "show", "jobs"]
    assert all(b.title and b.description for b in boards)


def test_get_boards_respects_limit(channel, client):
    boards = channel.get_boards(client, limit=3)
    assert [b.id for b in boards] == ["top", "new", "best"]


# ---------- threads (catalog) ----------

def test_get_threads_maps_story_list(channel, client):
    manifest = load_fixture(FIXTURES, "_manifest.json")
    routes, missing = _fixture_router([], list_body=manifest["topstories_ids"])
    client.session = FakeSession(routes)

    threads = channel.get_threads(client, "top")

    assert not missing, "test fixtures missed items: {0}".format(missing)
    assert len(threads) == len(manifest["topstories_ids"])
    # First story has url + title
    first = threads[0]
    assert first.id == str(manifest["story_id"])
    assert first.title
    assert first.comment  # link URL or text body


def test_get_threads_respects_catalog_size(channel, client):
    manifest = load_fixture(FIXTURES, "_manifest.json")
    routes, _ = _fixture_router([], list_body=manifest["topstories_ids"])
    client.session = FakeSession(routes)
    client.settings["catalog_size"] = "3"

    threads = channel.get_threads(client, "top")
    assert len(threads) == 3


def test_get_threads_unknown_board_raises(channel, client):
    client.session = FakeSession({})  # no routes — shouldn't be called
    with pytest.raises(ChannelsError):
        channel.get_threads(client, "bogus")


def test_get_threads_list_http_error_raises(channel, client):
    client.session = FakeSession({
        "hacker-news.firebaseio.com": FakeResponse(500),
    })
    with pytest.raises(ChannelsError):
        channel.get_threads(client, "top")


def test_get_threads_skips_null_items(channel, client):
    # Firebase returns null for unknown ids — ensure our plugin drops them
    # instead of crashing.
    routes = {
        "/topstories.json": FakeResponse(200, json_body=[999001, 999002]),
        "/item/999001.json": FakeResponse(200, json_body=None),
        "/item/999002.json": FakeResponse(200, json_body={
            "id": 999002, "type": "story", "title": "OK", "url": "https://x"}),
    }
    client.session = FakeSession(routes)
    threads = channel.get_threads(client, "top")
    assert [t.id for t in threads] == ["999002"]


# ---------- thread (comment tree) ----------

def test_get_thread_flattens_tree(channel, client):
    manifest = load_fixture(FIXTURES, "_manifest.json")
    routes, missing = _fixture_router([])
    client.session = FakeSession(routes)

    posts = channel.get_thread(client, "top", str(manifest["story_id"]))
    assert not missing, "test fixtures missed items: {0}".format(missing)

    # OP first
    assert posts[0].id == str(manifest["story_id"])
    # Each immediate child of OP appears as a post
    ids = [p.id for p in posts]
    for kid in manifest["story_kids"]:
        assert str(kid) in ids, "expected kid {0} in posts".format(kid)


def test_get_thread_populates_parent_replies(channel, client):
    manifest = load_fixture(FIXTURES, "_manifest.json")
    routes, _ = _fixture_router([])
    client.session = FakeSession(routes)

    posts = channel.get_thread(client, "top", str(manifest["story_id"]))
    by_id = {p.id: p for p in posts}

    op = by_id[str(manifest["story_id"])]
    # OP should list each first-level comment as a reply
    for kid in manifest["story_kids"]:
        assert str(kid) in op.replies, \
            "OP should track comment {0} in replies".format(kid)


def test_get_thread_missing_story_raises(channel, client):
    client.session = FakeSession({
        "hacker-news.firebaseio.com": FakeResponse(200, json_body=None),
    })
    with pytest.raises(ChannelsError):
        channel.get_thread(client, "top", "9999999")


def test_get_thread_skips_deleted_and_dead(channel, client):
    routes = {
        "/item/100.json": FakeResponse(200, json_body={
            "id": 100, "type": "story", "title": "x", "by": "a",
            "kids": [200, 201, 202]}),
        "/item/200.json": FakeResponse(200, json_body={
            "id": 200, "type": "comment", "deleted": True}),
        "/item/201.json": FakeResponse(200, json_body={
            "id": 201, "type": "comment", "dead": True, "text": "spam"}),
        "/item/202.json": FakeResponse(200, json_body={
            "id": 202, "type": "comment", "by": "ok", "text": "valid",
            "parent": 100}),
    }
    client.session = FakeSession(routes)
    posts = channel.get_thread(client, "top", "100")
    assert [p.id for p in posts] == ["100", "202"]


def test_get_thread_caps_at_max_comments(channel, client):
    # Build a wide tree with lots of comments
    kids = list(range(200, 230))
    routes = {
        "/item/100.json": FakeResponse(200, json_body={
            "id": 100, "type": "story", "title": "x", "kids": kids}),
    }
    for k in kids:
        routes["/item/{0}.json".format(k)] = FakeResponse(200, json_body={
            "id": k, "type": "comment", "by": "u", "text": "c",
            "parent": 100})
    client.session = FakeSession(routes)
    client.settings["max_comments"] = "5"

    posts = channel.get_thread(client, "top", "100")
    # OP + at most 5 comments = 6 total
    assert len(posts) == 6


def test_get_thread_html_entities_resolved(channel, client):
    # HN wraps URLs as <a href="URL">URL</a> (same URL inside and out). After
    # tag stripping the inner-text URL survives and entities like &#x2F; must
    # decode to "/".
    routes = {
        "/item/10.json": FakeResponse(200, json_body={
            "id": 10, "type": "story", "title": "t",
            "text": "<p>Gift: <a href=\"https:&#x2F;&#x2F;example.com\">"
                    "https:&#x2F;&#x2F;example.com</a></p>"
                    "<p>Second para.</p>",
            "kids": []}),
    }
    client.session = FakeSession(routes)
    posts = channel.get_thread(client, "top", "10")
    body = posts[0].comment
    assert "https://example.com" in body, \
        "numeric entity &#x2F; should be resolved: got {0!r}".format(body)
    assert "Second para." in body
    # paragraphs should be separated (not concatenated into one blob)
    gift_idx = body.index("Gift:")
    para_idx = body.index("Second para.")
    assert "\n" in body[gift_idx:para_idx], \
        "<p> boundaries should produce a newline between paragraphs"
    assert "<p>" not in body and "</p>" not in body


def test_get_thread_link_story_shows_url_in_body(channel, client):
    routes = {
        "/item/10.json": FakeResponse(200, json_body={
            "id": 10, "type": "story", "title": "t",
            "url": "https://example.com/article",
            "kids": []}),
    }
    client.session = FakeSession(routes)
    posts = channel.get_thread(client, "top", "10")
    assert "https://example.com/article" in posts[0].comment


def test_get_thread_long_comment_split(channel, client):
    long_text = "<p>" + ("lorem " * 400) + "</p>"
    routes = {
        "/item/10.json": FakeResponse(200, json_body={
            "id": 10, "type": "story", "title": "t", "text": long_text,
            "kids": []}),
    }
    client.session = FakeSession(routes)
    posts = channel.get_thread(client, "top", "10")
    assert len(posts) > 1, "expected split continuation posts"
    assert posts[0].id == "10"
    assert posts[1].id.startswith("10.")
    assert posts[1].title.startswith("... cont")


def test_channel_exports():
    import channels.hackernews as mod
    assert mod.CHANNEL_NAME == "hackernews"
    assert mod.CHANNEL_CLASS is HackernewsChannel
    assert isinstance(mod.CHANNEL_DESCRIPTION, str) and mod.CHANNEL_DESCRIPTION
