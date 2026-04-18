"""Live smoke tests that hit the real third-party services.

Skipped by default. Enable with: ``pytest --live``.

These do not assert exact content — only shape: that boards/threads/posts come
back in the expected structure. Failures here indicate either (a) the remote
service is down or rate-limiting us, or (b) they changed the API/HTML structure
and the plugin needs updating.
"""
import pytest

from channels.endchan import EndchanChannel
from channels.fourchan import FourChanChannel
from channels.spectrumcomputing import SpectrumComputing


pytestmark = pytest.mark.live


def _first_or_skip(items, what):
    if not items:
        pytest.skip("no {0} returned — upstream may be empty or rate-limited".format(what))
    return items[0]


# ---------- endchan ----------

def test_endchan_boards():
    ch = EndchanChannel()
    client = ch.new_client("live")
    boards = ch.get_boards(client, limit=5)
    assert boards, "endchan returned no boards"
    for b in boards:
        assert b.id and isinstance(b.id, str)
        assert b.description is not None


def test_endchan_threads_and_thread():
    ch = EndchanChannel()
    client = ch.new_client("live")
    boards = ch.get_boards(client, limit=20)
    board = _first_or_skip(boards, "boards")

    threads = ch.get_threads(client, board.id)
    if not threads:
        pytest.skip("board {0} has no threads right now".format(board.id))
    t = threads[0]
    assert t.id.isdigit() or t.id
    assert t.comment is not None

    posts = ch.get_thread(client, board.id, t.id)
    assert posts, "thread {0}/{1} returned no posts".format(board.id, t.id)
    assert posts[0].id


# ---------- 4chan ----------

def test_fourchan_boards():
    ch = FourChanChannel()
    client = ch.new_client("live")
    boards = ch.get_boards(client, limit=5)
    assert boards, "4chan returned no boards"
    for b in boards:
        assert b.id and isinstance(b.id, str)
        assert b.description


def test_fourchan_threads_and_thread():
    ch = FourChanChannel()
    client = ch.new_client("live")
    # /g/ is a stable, active board — a good pick for shape checks
    threads = ch.get_threads(client, "g")
    t = _first_or_skip(threads, "threads")
    assert t.id.isdigit()
    assert t.comment is not None

    posts = ch.get_thread(client, "g", t.id)
    assert posts, "thread g/{0} returned no posts".format(t.id)
    assert posts[0].id


# ---------- spectrumcomputing ----------
# Deactivated — site went login-walled in 2026-04. Re-enable once the plugin
# supports authenticated browsing or anonymous access is restored.

@pytest.mark.skip(reason="spectrumcomputing channel deactivated")
def test_spectrumcomputing_boards():
    ch = SpectrumComputing()
    client = ch.new_client("live")
    boards = ch.get_boards(client, limit=5)
    # NOTE: as of 2026-04, the anonymous forum listing is behind a login wall
    # ("forums accessible to logged in members only"). This assertion will
    # fail until that changes or the plugin gains auth support — which is the
    # signal the user wants from live tests.
    assert boards, (
        "spectrumcomputing returned no boards — either site is login-walled "
        "(anonymous access disabled), down, or the phpBB markup changed"
    )
    for b in boards:
        assert b.id and isinstance(b.id, str)


@pytest.mark.skip(reason="spectrumcomputing channel deactivated")
def test_spectrumcomputing_threads_and_thread():
    ch = SpectrumComputing()
    client = ch.new_client("live")
    boards = ch.get_boards(client, limit=5)
    board = _first_or_skip(boards, "boards")

    # keep this cheap — cap paging
    client.set_option("max_pages", "1")
    threads = ch.get_threads(client, board.id)
    t = _first_or_skip(threads, "threads")

    posts = ch.get_thread(client, board.id, t.id)
    assert posts, "thread f={0}&t={1} returned no posts".format(board.id, t.id)
