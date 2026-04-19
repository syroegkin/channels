from channels.base import Channel, ChannelsError, ChannelAttachment, ChannelBoard, ChannelThread
from channels.base import ChannelPost, SettingDefinition, Client, PostingError

import html
import requests


class LobstersClient(Client):
    def __init__(self, channel_name, client_id):
        super().__init__(channel_name, client_id)
        self.session = requests.Session()
        # Lobste.rs asks for an identifying UA; without one you can get 403'd.
        self.session.headers.update({
            "User-Agent": "channels-spectrum/0.5 (+https://github.com/syroegkin/channels)"
        })


# (board_id, display_title, endpoint_path)
#
# The first two are site-wide views; the rest are a curated tag selection.
# Tags are the site's own topic system (see https://lobste.rs/tags). Keeping
# the list short because the Spectrum UI shows one board per list row.
_BOARDS = [
    ("hottest",    "Hottest",        "/hottest.json"),
    ("newest",     "Newest",         "/newest.json"),
    ("programming","Programming",    "/t/programming.json"),
    ("rust",       "Rust",           "/t/rust.json"),
    ("c",          "C",              "/t/c.json"),
    ("unix",       "Unix",           "/t/unix.json"),
    ("linux",      "Linux",          "/t/linux.json"),
    ("security",   "Security",       "/t/security.json"),
    ("privacy",    "Privacy",        "/t/privacy.json"),
    ("retro",      "Retrocomputing", "/t/retrocomputing.json"),
    ("hardware",   "Hardware",       "/t/hardware.json"),
    ("ask",        "Ask",            "/t/ask.json"),
    ("show",       "Show",           "/t/show.json"),
]
_BOARD_PATH = {bid: path for bid, _, path in _BOARDS}


class LobstersChannel(Channel):
    """Lobste.rs read-only channel.

    Lobste.rs has a first-class JSON API (see https://lobste.rs/about). Every
    listing and story has a ``.json`` variant. No auth needed for read.

    Boards = {hottest, newest} plus a curated set of popular tags. Each tag's
    URL is the pattern ``/t/{tag}.json``.
    """

    base_url = "https://lobste.rs"
    catalog_size = 25           # stories per board view
    max_comments_per_thread = 80

    def name(self):
        return "lobsters"

    def new_client(self, client_id):
        return LobstersClient(self.name(), client_id)

    def get_setting_definitions(self, client):
        return [
            SettingDefinition("catalog_size",
                              "Stories per page (default {0})".format(self.catalog_size)),
            SettingDefinition("max_comments",
                              "Max comments per thread (default {0})".format(
                                  self.max_comments_per_thread)),
        ]

    # -- helpers --------------------------------------------------------

    @staticmethod
    def _clean_text(s):
        if not s:
            return ""
        # Lobste.rs descriptions and comments come back as HTML fragments (<p>,
        # <a>, <code>…). Turn paragraph breaks into blank lines before stripping
        # so paragraphs don't collide.
        s = s.replace("<p>", "\n\n").replace("</p>", "")
        s = Channel.strip_html(s)
        # strip_html handles a few named entities; catch the rest
        # (numeric refs like &#x2F;, &mdash;, …) with stdlib unescape.
        s = html.unescape(s)
        return s

    def _int_setting(self, client, key, default):
        try:
            v = int(client.settings.get(key, "") or default)
            return v if v > 0 else default
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _user_name(val):
        # Depending on endpoint, ``submitter_user`` / ``user`` is either a
        # plain string (modern API) or an object with ``username``.
        if val is None:
            return "anon"
        if isinstance(val, str):
            return val
        if isinstance(val, dict):
            return val.get("username") or "anon"
        return "anon"

    # -- API ------------------------------------------------------------

    def get_boards(self, client, limit):
        boards = [ChannelBoard(bid, title, title) for bid, title, _ in _BOARDS]
        if limit:
            boards = boards[:limit]
        return boards

    def get_threads(self, client, board):
        path = _BOARD_PATH.get(board)
        if path is None:
            raise ChannelsError(ChannelsError.UNKNOWN_ERROR)

        r = client.session.get(self.base_url + path)
        if r.status_code != 200:
            raise ChannelsError(ChannelsError.UNKNOWN_ERROR)
        stories = r.json() or []

        size = self._int_setting(client, "catalog_size", self.catalog_size)
        stories = stories[:size]

        threads = []
        for s in stories:
            sid = s.get("short_id")
            if not sid:
                continue
            t = ChannelThread(sid)
            t.title = s.get("title")
            t.num_replies = s.get("comment_count") or 0
            # Lobste.rs returns ISO8601 strings; converting to an int epoch is
            # expensive and not currently displayed. Leave as 0 like HN.
            t.date = 0

            url = s.get("url")
            body = s.get("description_plain") or ""
            if not body and s.get("description"):
                body = self._clean_text(s["description"])
            # For link stories the URL is the meaningful content; surface it
            # above any description text.
            if url and body:
                body = "{0}\n\n{1}".format(url, body)
            elif url:
                body = url
            t.comment = body
            threads.append(t)
        return threads

    def get_thread(self, client, board, thread):
        r = client.session.get("{0}/s/{1}.json".format(self.base_url, thread))
        if r.status_code != 200:
            raise ChannelsError(ChannelsError.UNKNOWN_ERROR)
        data = r.json() or {}

        posts = []
        posts_by_id = {}
        max_comments = self._int_setting(
            client, "max_comments", self.max_comments_per_thread)

        def _emit(item_id, title, body, parent_id):
            body = body or ""
            parent_post = posts_by_id.get(parent_id) if parent_id else None
            for index, strip in enumerate(Channel.split_comment(body)):
                if index == 0:
                    pid = item_id
                    p = ChannelPost(pid)
                    p.title = title
                    if parent_post is not None:
                        parent_post.replies.append(pid)
                else:
                    pid = "{0}.{1}".format(item_id, index)
                    p = ChannelPost(pid)
                    p.title = "... cont {0}".format(index)
                    posts_by_id[item_id].replies.append(pid)
                p.comment = strip
                posts.append(p)
                posts_by_id[p.id] = p
                if len(posts) >= max_comments + 1:  # +1 for OP
                    return False
            return True

        # OP: compose the story "post" from title + url + description
        op_id = data.get("short_id") or thread
        op_url = data.get("url")
        op_desc = data.get("description_plain") or ""
        if not op_desc and data.get("description"):
            op_desc = self._clean_text(data["description"])
        if op_url and op_desc:
            op_body = "{0}\n\n{1}".format(op_url, op_desc)
        elif op_url:
            op_body = op_url
        else:
            op_body = op_desc
        op_title = data.get("title") or "(no title)"
        submitter = self._user_name(data.get("submitter_user"))
        if submitter:
            op_title = "{0} - by {1}".format(op_title, submitter)
        _emit(op_id, op_title, op_body, parent_id=None)

        # Comments come pre-flattened in depth-first order; each has
        # parent_comment referring to a ``short_id`` (or None/empty for
        # top-level). That maps cleanly to our parent->replies link.
        for c in data.get("comments") or []:
            if len(posts) >= max_comments + 1:
                break
            cid = c.get("short_id")
            if not cid:
                continue
            author = self._user_name(c.get("user") or c.get("commenting_user"))
            body = self._clean_text(c.get("comment") or c.get("comment_plain") or "")
            parent = c.get("parent_comment") or op_id
            # parent_comment can come as an object with short_id on older
            # responses; normalise.
            if isinstance(parent, dict):
                parent = parent.get("short_id") or op_id
            if not _emit(cid, "by {0}".format(author), body, parent_id=parent):
                break

        return posts


CHANNEL_NAME = "lobsters"
CHANNEL_CLASS = LobstersChannel
CHANNEL_DESCRIPTION = "Lobste.rs - invite-only tech link aggregator."
