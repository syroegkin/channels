from channels.base import Channel, ChannelsError, ChannelAttachment, ChannelBoard, ChannelThread
from channels.base import ChannelPost, SettingDefinition, Client, PostingError

import concurrent.futures
import html
import re
import requests


class HackernewsClient(Client):
    def __init__(self, channel_name, client_id):
        super().__init__(channel_name, client_id)
        self.session = requests.Session()


# (board_id, display_title, firebase_endpoint_name)
_BOARDS = [
    ("top",  "Top stories",   "topstories"),
    ("new",  "New stories",   "newstories"),
    ("best", "Best stories",  "beststories"),
    ("ask",  "Ask HN",        "askstories"),
    ("show", "Show HN",       "showstories"),
    ("jobs", "Jobs",          "jobstories"),
]
_BOARD_ENDPOINT = {bid: ep for bid, _, ep in _BOARDS}


class HackernewsChannel(Channel):
    """HackerNews read-only channel.

    HN doesn't have boards, so we expose its story-list endpoints (top / new /
    best / Ask / Show / Jobs) as pseudo-boards. Threads are stories; posts are
    the story's comment tree, flattened DFS with parent->child links surfaced
    via each post's ``replies``.
    """

    base_url = "https://hacker-news.firebaseio.com/v0"
    catalog_size = 30           # stories per "board view"
    max_comments_per_thread = 60
    parallel_fetches = 8

    def name(self):
        return "hackernews"

    def new_client(self, client_id):
        return HackernewsClient(self.name(), client_id)

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
        # HN body text uses <p> for paragraphs without trailing text; turn them
        # into blank lines so ``strip_html`` doesn't run paragraphs together.
        s = s.replace("<p>", "\n\n").replace("</p>", "")
        s = Channel.strip_html(s)
        # strip_html handles the five common named entities; HN also emits
        # numeric refs like &#x2F;. html.unescape catches the rest.
        s = html.unescape(s)
        return s

    def _item_url(self, item_id):
        return "{0}/item/{1}.json".format(self.base_url, item_id)

    def _get_item(self, client, item_id):
        r = client.session.get(self._item_url(item_id))
        if r.status_code != 200:
            return None
        data = r.json()
        # Firebase returns ``null`` for unknown ids, which requests.json()
        # surfaces as None.
        return data if isinstance(data, dict) else None

    def _get_items_parallel(self, client, ids):
        if not ids:
            return []
        out = [None] * len(ids)
        with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.parallel_fetches) as pool:
            futures = {pool.submit(self._get_item, client, i): idx
                       for idx, i in enumerate(ids)}
            for fut in concurrent.futures.as_completed(futures):
                out[futures[fut]] = fut.result()
        return out

    def _int_setting(self, client, key, default):
        try:
            v = int(client.settings.get(key, "") or default)
            return v if v > 0 else default
        except (ValueError, TypeError):
            return default

    # -- API ------------------------------------------------------------

    def get_boards(self, client, limit):
        boards = [ChannelBoard(bid, title, title) for bid, title, _ in _BOARDS]
        if limit:
            boards = boards[:limit]
        return boards

    def get_threads(self, client, board):
        endpoint = _BOARD_ENDPOINT.get(board)
        if endpoint is None:
            raise ChannelsError(ChannelsError.UNKNOWN_ERROR)

        r = client.session.get("{0}/{1}.json".format(self.base_url, endpoint))
        if r.status_code != 200:
            raise ChannelsError(ChannelsError.UNKNOWN_ERROR)
        ids = r.json() or []

        size = self._int_setting(client, "catalog_size", self.catalog_size)
        ids = ids[:size]

        threads = []
        for item in self._get_items_parallel(client, ids):
            if not item:
                continue
            sid = item.get("id")
            if sid is None:
                continue
            t = ChannelThread(str(sid))
            t.title = item.get("title")
            t.num_replies = item.get("descendants") or 0
            t.date = item.get("time") or 0

            text = item.get("text") or ""
            url = item.get("url")
            # Link stories: the URL is the whole "body". Ask/Show have text.
            if url and text:
                body = "{0}\n\n{1}".format(url, text)
            elif url:
                body = url
            else:
                body = text
            t.comment = self._clean_text(body)
            threads.append(t)
        return threads

    def get_thread(self, client, board, thread):
        story = self._get_item(client, thread)
        if not story:
            raise ChannelsError(ChannelsError.UNKNOWN_ERROR)

        posts = []
        posts_by_id = {}
        max_comments = self._int_setting(
            client, "max_comments", self.max_comments_per_thread)

        def _emit(item_id, title, body, parent_id):
            """Emit one post (plus '... cont N' continuations for long bodies)."""
            body = body or ""
            parent_post = posts_by_id.get(str(parent_id)) if parent_id else None
            for index, strip in enumerate(Channel.split_comment(body)):
                if index == 0:
                    pid = str(item_id)
                    p = ChannelPost(pid)
                    p.title = title
                    if parent_post is not None:
                        parent_post.replies.append(pid)
                else:
                    pid = "{0}.{1}".format(item_id, index)
                    p = ChannelPost(pid)
                    p.title = "... cont {0}".format(index)
                    posts_by_id[str(item_id)].replies.append(pid)
                p.comment = strip
                posts.append(p)
                posts_by_id[p.id] = p
                if len(posts) >= max_comments + 1:  # +1 for OP
                    return False
            return True

        # OP: compose title/body from the story item
        url = story.get("url")
        story_text = story.get("text") or ""
        if url and story_text:
            op_body = "{0}\n\n{1}".format(url, story_text)
        elif url:
            op_body = url
        else:
            op_body = story_text
        op_title = story.get("title") or "(no title)"
        if story.get("by"):
            op_title = "{0} — by {1}".format(op_title, story["by"])
        _emit(story.get("id"), op_title, self._clean_text(op_body), parent_id=None)

        # DFS the comment tree. Fetch each level in parallel for speed.
        pending = list(story.get("kids") or [])
        while pending and len(posts) < max_comments + 1:
            level_ids = pending
            pending = []
            items = self._get_items_parallel(client, level_ids)
            for cid, item in zip(level_ids, items):
                if len(posts) >= max_comments + 1:
                    break
                if not item or item.get("deleted") or item.get("dead"):
                    continue
                if item.get("type") != "comment":
                    continue
                author = item.get("by") or "anon"
                body = self._clean_text(item.get("text") or "")
                parent = item.get("parent") or story.get("id")
                if not _emit(item.get("id"), "by {0}".format(author),
                             body, parent_id=parent):
                    break
                pending.extend(item.get("kids") or [])

        return posts


CHANNEL_NAME = "hackernews"
CHANNEL_CLASS = HackernewsChannel
CHANNEL_DESCRIPTION = "HackerNews — tech news and discussion aggregator."
