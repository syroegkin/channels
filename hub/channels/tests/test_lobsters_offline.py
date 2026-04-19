import pytest

from channels.lobsters import LobstersChannel
from channels.base import ChannelsError

from .conftest import FakeSession, FakeResponse, load_fixture


FIXTURES = "lobsters"


@pytest.fixture
def channel():
    return LobstersChannel()


@pytest.fixture
def client(channel):
    return channel.new_client("offline-test")


def _install(client, routes):
    client.session = FakeSession(routes)
    return client.session


def test_channel_exports():
    # The hub's auto-discovery depends on these three module attributes.
    from channels import lobsters
    assert lobsters.CHANNEL_NAME == "lobsters"
    assert lobsters.CHANNEL_CLASS is LobstersChannel
    assert lobsters.CHANNEL_DESCRIPTION


def test_get_boards_has_hottest_and_newest(channel, client):
    boards = channel.get_boards(client, limit=0)
    ids = [b.id for b in boards]
    assert "hottest" in ids
    assert "newest" in ids
    # Sanity on the curated tag set; these are stable tags on the real site.
    for expected in ("programming", "rust", "retro", "ask", "show"):
        assert expected in ids


def test_get_boards_respects_limit(channel, client):
    boards = channel.get_boards(client, limit=3)
    assert len(boards) == 3


def test_get_threads_unknown_board_raises(channel, client):
    _install(client, {})  # no routes needed; we should fail before HTTP
    with pytest.raises(ChannelsError):
        channel.get_threads(client, board="no-such-thing")


def test_get_threads_parses_hottest(channel, client):
    body = load_fixture(FIXTURES, "hottest.json")
    _install(client, {"/hottest.json": FakeResponse(200, json_body=body)})

    threads = channel.get_threads(client, board="hottest")
    assert len(threads) == 3

    # Link story: URL shows above body
    first = threads[0]
    assert first.id == "abc001"
    assert first.title == "A link story about retro computing"
    assert first.num_replies == 42 or first.num_replies == 3  # comment_count
    # Be strict: we use comment_count, not score
    assert first.num_replies == 3
    assert "https://example.com/retro-post" in first.comment

    # Text story (Ask-style): description_plain shows, no URL
    second = threads[1]
    assert second.id == "def002"
    assert "ZX Spectrum" in second.comment


def test_get_threads_http_error_raises(channel, client):
    _install(client, {"/hottest.json": FakeResponse(500, content=b"boom")})
    with pytest.raises(ChannelsError):
        channel.get_threads(client, board="hottest")


def test_get_threads_respects_catalog_size_setting(channel, client):
    body = load_fixture(FIXTURES, "hottest.json")
    _install(client, {"/hottest.json": FakeResponse(200, json_body=body)})
    client.settings["catalog_size"] = "1"
    threads = channel.get_threads(client, board="hottest")
    assert len(threads) == 1


def test_get_thread_parses_story_and_comments(channel, client):
    body = load_fixture(FIXTURES, "story_def002.json")
    _install(client, {"/s/def002.json": FakeResponse(200, json_body=body)})

    posts = channel.get_thread(client, board="hottest", thread="def002")
    # OP + 2 comments
    assert len(posts) == 3
    assert posts[0].id == "def002"
    assert "by bob" in posts[0].title
    assert "ZX Spectrum" in posts[0].comment

    # Reply linkage: cmt001 is at indent 1 (top-level → OP's reply)
    assert "cmt001" in posts[0].replies
    # cmt002 is a child of cmt001
    cmt1 = next(p for p in posts if p.id == "cmt001")
    assert "cmt002" in cmt1.replies
    assert "by dave" in cmt1.title

    # Non-ASCII transliteration sanity: entity decoding happened
    assert "&" in cmt1.comment


def test_get_thread_http_error_raises(channel, client):
    _install(client, {"/s/abc.json": FakeResponse(404, content=b"nope")})
    with pytest.raises(ChannelsError):
        channel.get_thread(client, board="hottest", thread="abc")


def test_get_thread_respects_max_comments_setting(channel, client):
    body = load_fixture(FIXTURES, "story_def002.json")
    _install(client, {"/s/def002.json": FakeResponse(200, json_body=body)})
    client.settings["max_comments"] = "1"  # OP + 1 comment max
    posts = channel.get_thread(client, board="hottest", thread="def002")
    assert len(posts) == 2
