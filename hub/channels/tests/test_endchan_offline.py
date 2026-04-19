import pytest
from unidecode import unidecode

from channels.endchan import EndchanChannel
from channels.base import ChannelsError

from .conftest import FakeSession, FakeResponse, load_fixture


@pytest.fixture
def channel():
    return EndchanChannel()


@pytest.fixture
def client(channel):
    return channel.new_client("offline-test")


def _install_session(client, routes):
    client.session = FakeSession(routes)
    return client.session


def test_get_boards_parses_fixture(channel, client):
    body = load_fixture("endchan", "boards_page1.json")
    body["pageCount"] = 1  # force single-page loop
    _install_session(client, {"boards.js": FakeResponse(200, json_body=body)})

    boards = channel.get_boards(client, limit=0)

    assert len(boards) == len(body["boards"])
    first = boards[0]
    assert first.id == body["boards"][0]["boardUri"]
    # Titles/descriptions are transliterated to ASCII for the Spectrum client.
    assert first.title == unidecode(body["boards"][0]["boardName"])
    assert first.description == unidecode(body["boards"][0]["boardDescription"])


def test_get_boards_respects_limit(channel, client):
    body = load_fixture("endchan", "boards_page1.json")
    body["pageCount"] = 1
    _install_session(client, {"boards.js": FakeResponse(200, json_body=body)})

    boards = channel.get_boards(client, limit=3)
    assert len(boards) == 3


def test_get_boards_paginates(channel, client):
    page1 = {
        "pageCount": 2,
        "boards": [
            {"boardUri": "a", "boardName": "A", "boardDescription": "alpha"},
            {"boardUri": "b", "boardName": "B", "boardDescription": "beta"},
        ],
    }
    page2 = {
        "pageCount": 2,
        "boards": [
            {"boardUri": "c", "boardName": "C", "boardDescription": "gamma"},
        ],
    }
    call_count = {"n": 0}

    def handler(url, params=None, **kw):
        call_count["n"] += 1
        page = params.get("page") if params else "1"
        return FakeResponse(200, json_body=page1 if page == "1" else page2)

    _install_session(client, {"boards.js": handler})
    boards = channel.get_boards(client, limit=0)
    assert call_count["n"] == 2
    assert [b.id for b in boards] == ["a", "b", "c"]


def test_get_boards_http_error_raises(channel, client):
    _install_session(client, {"boards.js": FakeResponse(500, content=b"boom")})
    with pytest.raises(ChannelsError):
        channel.get_boards(client, limit=0)


def test_get_boards_skips_entries_missing_uri(channel, client):
    body = {
        "pageCount": 1,
        "boards": [
            {"boardUri": "good", "boardName": "OK", "boardDescription": "fine"},
            {"boardName": "Missing URI"},
        ],
    }
    _install_session(client, {"boards.js": FakeResponse(200, json_body=body)})
    boards = channel.get_boards(client, limit=0)
    assert [b.id for b in boards] == ["good"]


def test_get_threads_maps_fields(channel, client):
    catalog = load_fixture("endchan", "tech_catalog.json")
    _install_session(client, {"catalog.json": FakeResponse(200, json_body=catalog)})

    threads = channel.get_threads(client, "tech")

    assert len(threads) == len(catalog)
    for src, got in zip(catalog, threads):
        assert got.id == str(src["threadId"])
        assert got.num_replies == (src.get("postCount") or 0)
        if src.get("thumb"):
            assert got.attachments, "expected thumbnail to become an attachment"
            assert got.attachments[0].url.startswith("https://endchan.net")
        else:
            assert got.attachments == []


def test_get_threads_http_error_raises(channel, client):
    _install_session(client, {"catalog.json": FakeResponse(404)})
    with pytest.raises(ChannelsError):
        channel.get_threads(client, "tech")


def test_get_threads_skips_entries_missing_id(channel, client):
    _install_session(client, {
        "catalog.json": FakeResponse(200, json_body=[
            {"threadId": 1, "message": "ok"},
            {"message": "no threadId"},
        ]),
    })
    threads = channel.get_threads(client, "x")
    assert [t.id for t in threads] == ["1"]


def test_get_thread_handles_op_and_replies(channel, client):
    thread = load_fixture("endchan", "tech_thread.json")
    _install_session(client, {"res/": FakeResponse(200, json_body=thread)})

    posts = channel.get_thread(client, "tech", str(thread["threadId"]))

    assert posts, "expected at least the OP post"
    # First post id should match the OP thread id (continuations are "<id>.N")
    op_id = str(thread["threadId"])
    assert posts[0].id == op_id
    # Every returned post id is either a raw post id or <id>.N continuation
    assert all("." in p.id or p.id.isdigit() for p in posts)


def test_get_thread_cross_references(channel, client):
    # Synthesize a thread where reply references another post by >>id
    thread = {
        "threadId": 100,
        "subject": "OP",
        "message": "Hello world",
        "files": [],
        "posts": [
            {"postId": 101, "message": "first reply", "files": []},
            {"postId": 102, "message": ">>101\nreferencing the first reply", "files": []},
        ],
    }
    _install_session(client, {"res/": FakeResponse(200, json_body=thread)})
    posts = channel.get_thread(client, "b", "100")
    by_id = {p.id: p for p in posts}
    assert "102" in by_id["101"].replies, \
        "post 101 should have post 102 in its replies list"


def test_get_thread_splits_long_comments(channel, client):
    # A long single-line message forces split_comment to emit "... cont N" continuations
    long_body = "word " * 600  # ~3000 chars -> multiple 44-col lines
    thread = {
        "threadId": 1,
        "subject": "long",
        "message": long_body,
        "files": [],
        "posts": [],
    }
    _install_session(client, {"res/": FakeResponse(200, json_body=thread)})
    posts = channel.get_thread(client, "b", "1")
    assert len(posts) > 1, "expected at least one continuation post"
    assert posts[0].id == "1"
    assert posts[1].id.startswith("1.")
    assert posts[1].title.startswith("... cont")


def test_get_thread_attachment_url_absolutized(channel, client):
    thread = {
        "threadId": 9,
        "message": "has image",
        "files": [
            {"path": "/.media/abc-imagejpeg.jpg", "mime": "image/jpeg"},
        ],
        "posts": [],
    }
    _install_session(client, {"res/": FakeResponse(200, json_body=thread)})
    posts = channel.get_thread(client, "b", "9")
    assert posts[0].attachments[0].url == "https://endchan.net/.media/abc-imagejpeg.jpg"


def test_get_thread_preserves_absolute_attachment_url(channel, client):
    thread = {
        "threadId": 9,
        "message": "already absolute",
        "files": [{"path": "https://cdn.example.com/x.jpg"}],
        "posts": [],
    }
    _install_session(client, {"res/": FakeResponse(200, json_body=thread)})
    posts = channel.get_thread(client, "b", "9")
    assert posts[0].attachments[0].url == "https://cdn.example.com/x.jpg"


def test_channel_exports():
    import channels.endchan as mod
    assert mod.CHANNEL_NAME == "endchan"
    assert mod.CHANNEL_CLASS is EndchanChannel
    assert isinstance(mod.CHANNEL_DESCRIPTION, str) and mod.CHANNEL_DESCRIPTION
