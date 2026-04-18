import pytest

from channels.fourchan import FourChanChannel
from channels.base import ChannelsError

from .conftest import FakeSession, FakeResponse, load_fixture


@pytest.fixture
def channel():
    return FourChanChannel()


@pytest.fixture
def client(channel):
    return channel.new_client("offline-test")


def _install_session(client, routes):
    client.session = FakeSession(routes)
    return client.session


def test_get_boards_parses_fixture(channel, client):
    body = load_fixture("fourchan", "boards.json")
    _install_session(client, {"boards.json": FakeResponse(200, json_body=body)})

    boards = channel.get_boards(client, limit=0)

    assert len(boards) == len(body["boards"])
    src = body["boards"][0]
    assert boards[0].id == src["board"]
    # 4chan plugin stores board name in .description and leaves title None
    assert boards[0].title is None
    assert boards[0].description == src["title"]


def test_get_boards_http_error_raises(channel, client):
    _install_session(client, {"boards.json": FakeResponse(503)})
    with pytest.raises(ChannelsError):
        channel.get_boards(client, limit=0)


def test_get_threads_parses_fixture(channel, client):
    catalog = load_fixture("fourchan", "g_catalog.json")
    _install_session(client, {"catalog.json": FakeResponse(200, json_body=catalog)})

    threads = channel.get_threads(client, "g")

    total_with_com = sum(
        1 for page in catalog for t in page["threads"]
        if "no" in t and "com" in t
    )
    assert len(threads) == total_with_com, \
        "plugin should only emit threads with a comment body"

    for t in threads:
        assert t.id.isdigit()
        assert t.comment is not None
        # strip_html should remove any <tag>
        assert "<a" not in t.comment and "<br>" not in t.comment


def test_get_threads_skips_entries_without_comment(channel, client):
    catalog = [{"page": 1, "threads": [
        {"no": 1, "com": "hello", "sub": "hi", "replies": 2},
        {"no": 2, "sub": "no comment field"},
        {"com": "no 'no' field"},
    ]}]
    _install_session(client, {"catalog.json": FakeResponse(200, json_body=catalog)})
    threads = channel.get_threads(client, "g")
    assert [t.id for t in threads] == ["1"]
    assert threads[0].num_replies == 2
    assert threads[0].title == "hi"


def test_get_threads_http_error_raises(channel, client):
    _install_session(client, {"catalog.json": FakeResponse(404)})
    with pytest.raises(ChannelsError):
        channel.get_threads(client, "zz")


def test_get_thread_cross_references(channel, client):
    thread = {"posts": [
        {"no": 100, "com": "original"},
        {"no": 101, "com": "<a class=\"quotelink\">&gt;&gt;100</a><br>referencing OP"},
    ]}
    _install_session(client, {"/thread/": FakeResponse(200, json_body=thread)})

    posts = channel.get_thread(client, "g", "100")
    by_id = {p.id: p for p in posts}
    assert "101" in by_id["100"].replies, \
        "4chan >>100 reference from post 101 should be tracked on post 100"


def test_get_thread_attachment_url_composed(channel, client):
    thread = {"posts": [
        {"no": 100, "com": "with pic", "tim": 1234567890, "ext": ".jpg"},
    ]}
    _install_session(client, {"/thread/": FakeResponse(200, json_body=thread)})

    posts = channel.get_thread(client, "g", "100")
    assert posts[0].attachments, "expected attachment"
    assert posts[0].attachments[0].url == "https://i.4cdn.org/g/1234567890.jpg"


def test_get_thread_continuations_attributed_to_op(channel, client):
    long_body = "lorem ipsum " * 500
    thread = {"posts": [{"no": 100, "com": long_body}]}
    _install_session(client, {"/thread/": FakeResponse(200, json_body=thread)})

    posts = channel.get_thread(client, "g", "100")
    assert len(posts) > 1
    assert posts[0].id == "100"
    assert all(p.id.startswith("100") for p in posts)
    assert posts[1].title.startswith("... cont")


def test_get_thread_http_error_raises(channel, client):
    _install_session(client, {"/thread/": FakeResponse(500)})
    with pytest.raises(ChannelsError):
        channel.get_thread(client, "g", "1")


def test_channel_exports():
    import channels.fourchan as mod
    assert mod.CHANNEL_NAME == "4chan"
    assert mod.CHANNEL_CLASS is FourChanChannel
    assert isinstance(mod.CHANNEL_DESCRIPTION, str) and mod.CHANNEL_DESCRIPTION
