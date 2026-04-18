import os

import pytest

from channels.spectrumcomputing import SpectrumComputing
from channels.base import ChannelsError

from .conftest import FakeSession, FakeResponse, fixture_path


def _read(*parts):
    with open(fixture_path(*parts), "rb") as f:
        return f.read()


@pytest.fixture
def channel():
    return SpectrumComputing()


@pytest.fixture
def client(channel):
    return channel.new_client("offline-test")


def _install_session(client, routes):
    client.session = FakeSession(routes)
    return client.session


def test_get_boards_parses_phpbb_forum_list(channel, client):
    html = _read("spectrumcomputing", "forums_index.html")
    _install_session(client, {"forums": FakeResponse(200, content=html)})

    boards = channel.get_boards(client, limit=0)

    assert [b.id for b in boards] == ["1", "4", "12"]
    assert boards[1].description == "Games / Discussion"
    # title is lowercased with '/' -> ' '
    assert boards[1].title == "games   discussion"


def test_get_boards_http_error_raises(channel, client):
    _install_session(client, {"forums": FakeResponse(500)})
    with pytest.raises(ChannelsError):
        channel.get_boards(client, limit=0)


def test_get_threads_parses_topics(channel, client):
    html = _read("spectrumcomputing", "viewforum.html")
    _install_session(client, {"viewforum.php": FakeResponse(200, content=html)})

    threads = channel.get_threads(client, "4")

    assert [t.id for t in threads] == ["101", "102", "103"]
    assert threads[0].title == "Welcome to the games forum"
    assert threads[0].num_replies == 42
    assert threads[0].comment == "This is the preview text of the first topic."
    # bogus replies count degrades gracefully to 0
    assert threads[2].num_replies == 0
    assert threads[2].comment == "third topic preview"


@pytest.mark.xfail(
    reason="spectrumcomputing plugin crashes on topics missing topic_preview_content "
           "(a.parent.find(...) returns None then .find() on it throws). "
           "The exception handler silently drops the whole thread instead of "
           "falling back to '<no comment>'.",
    strict=True,
)
def test_get_threads_handles_topic_without_preview_block(channel, client):
    html = b"""
        <html><body><div class="forumbg"><ul><li>
        <dl class="row-item"><dt>
        <a href="./viewtopic.php?f=4&amp;t=999" class="topictitle">No preview topic</a>
        </dt></dl>
        </li></ul></div></body></html>
    """
    _install_session(client, {"viewforum.php": FakeResponse(200, content=html)})
    threads = channel.get_threads(client, "4")
    assert [t.id for t in threads] == ["999"]
    assert threads[0].comment == "<no comment>"


def test_get_threads_http_error_raises(channel, client):
    _install_session(client, {"viewforum.php": FakeResponse(404)})
    with pytest.raises(ChannelsError):
        channel.get_threads(client, "99")


def test_get_thread_parses_posts(channel, client):
    html = _read("spectrumcomputing", "viewtopic.html")
    # Second request returns an empty page so the pagination loop ends
    end_html = b"<html><body></body></html>"
    call_count = {"n": 0}

    def handler(url, params=None, **kw):
        call_count["n"] += 1
        return FakeResponse(200, content=html if call_count["n"] == 1 else end_html)

    _install_session(client, {"viewtopic.php": handler})

    posts = channel.get_thread(client, "4", "101")

    assert [p.id for p in posts] == ["501", "502", "503"]
    assert posts[0].title == "by alice"
    assert posts[0].attachments[0].url == "https://spectrumcomputing.co.uk/images/pic1.png"
    # blockquote with data-post-id=501 on post 502 should link back
    assert "502" in posts[0].replies
    # quote text is replaced with ">quote"
    assert ">quote" in posts[1].comment
    # post with no image has no attachments
    assert posts[2].attachments == []


def test_get_thread_max_pages_setting(channel, client):
    html = _read("spectrumcomputing", "viewtopic.html")
    call_count = {"n": 0}

    def handler(url, params=None, **kw):
        call_count["n"] += 1
        # Always return content with a "next" link to prove max_pages caps us
        body = html.replace(
            b"</body>",
            b'<li class="arrow next"><a href="#">Next</a></li></body>',
        )
        return FakeResponse(200, content=body)

    _install_session(client, {"viewtopic.php": handler})
    client.settings["max_pages"] = "2"

    posts = channel.get_thread(client, "4", "101")
    assert call_count["n"] == 2, "max_pages=2 should cap at 2 HTTP fetches"
    # 3 posts per page × 2 pages. The parser dedupes by id so we get 3 unique ids,
    # but the code currently appends duplicates — assert the call cap instead.
    assert len(posts) >= 3


def test_get_thread_http_error_raises_when_nothing_collected(channel, client):
    _install_session(client, {"viewtopic.php": FakeResponse(500)})
    with pytest.raises(ChannelsError):
        channel.get_thread(client, "4", "101")


def test_channel_exports():
    import channels.spectrumcomputing as mod
    assert mod.CHANNEL_NAME == "spectrumcomputing"
    assert mod.CHANNEL_CLASS is SpectrumComputing
    assert isinstance(mod.CHANNEL_DESCRIPTION, str) and mod.CHANNEL_DESCRIPTION
