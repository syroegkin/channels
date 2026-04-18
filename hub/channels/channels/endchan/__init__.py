from channels.base import Channel, ChannelsError, ChannelAttachment, ChannelBoard, ChannelThread
from channels.base import ChannelPost, SettingDefinition, Client, PostingError

import requests
import re


class EndchanClient(Client):
    def __init__(self, channel_name, client_id):
        super().__init__(channel_name, client_id)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0"})


class EndchanChannel(Channel):
    base_url = "https://endchan.net"
    post_reply_pattern = re.compile(r'>>([0-9]+)', re.MULTILINE)

    def name(self):
        return "endchan"

    def new_client(self, client_id):
        return EndchanClient(self.name(), client_id)

    def _abs_url(self, path):
        if not path:
            return None
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return EndchanChannel.base_url + path

    def get_boards(self, client, limit):
        boards = []
        page = 1
        while True:
            r = client.session.get(
                EndchanChannel.base_url + "/boards.js",
                params={"json": "1", "page": str(page)})
            if r.status_code != 200:
                if not boards:
                    raise ChannelsError(ChannelsError.UNKNOWN_ERROR)
                break

            data = r.json()
            entries = data.get("boards") or []
            if not entries:
                break

            for b in entries:
                uri = b.get("boardUri")
                if not uri:
                    continue
                title = b.get("boardName") or uri
                description = b.get("boardDescription") or title
                boards.append(ChannelBoard(uri, title, description))
                if limit and len(boards) >= limit:
                    return boards

            page_count = data.get("pageCount") or 1
            if page >= page_count:
                break
            page += 1

        return boards

    def get_threads(self, client, board):
        r = client.session.get(
            "{0}/{1}/catalog.json".format(EndchanChannel.base_url, board))
        if r.status_code != 200:
            raise ChannelsError(ChannelsError.UNKNOWN_ERROR)

        threads = []
        for t in r.json():
            thread_id = t.get("threadId")
            if thread_id is None:
                continue

            result = ChannelThread(str(thread_id))
            if t.get("subject"):
                result.title = t["subject"]
            result.num_replies = t.get("postCount") or 0

            body = t.get("message") or t.get("markdown") or ""
            result.comment = Channel.strip_html(body)

            thumb = t.get("thumb")
            if thumb:
                result.attachments.append(ChannelAttachment(self._abs_url(thumb)))

            threads.append(result)

        return threads

    def get_thread(self, client, board, thread):
        r = client.session.get(
            "{0}/{1}/res/{2}.json".format(EndchanChannel.base_url, board, thread))
        if r.status_code != 200:
            raise ChannelsError(ChannelsError.UNKNOWN_ERROR)

        data = r.json()

        posts = []
        posts_by_id = {}

        op = dict(data)
        op["postId"] = data.get("threadId")
        all_posts = [op]
        all_posts.extend(data.get("posts") or [])

        for post in all_posts:
            post_id_num = post.get("postId")
            if post_id_num is None:
                continue

            body = post.get("message") or post.get("markdown") or ""
            body = Channel.strip_html(body)
            files = post.get("files") or []
            subject = post.get("subject")

            for index, strip in enumerate(Channel.split_comment(body)):
                post_id = str(post_id_num) if index == 0 \
                    else "{0}.{1}".format(post_id_num, index)
                result_post = ChannelPost(post_id)

                if index == 0:
                    if subject:
                        result_post.title = subject
                    for f in files:
                        url = self._abs_url(f.get("path"))
                        if url:
                            result_post.attachments.append(ChannelAttachment(url))
                    for m in re.finditer(EndchanChannel.post_reply_pattern, strip):
                        ref = m.group(1)
                        if ref in posts_by_id:
                            posts_by_id[ref].replies.append(result_post.id)
                else:
                    result_post.title = "... cont {0}".format(index)
                    posts_by_id[str(post_id_num)].replies.append(result_post.id)

                result_post.comment = strip
                posts.append(result_post)
                posts_by_id[result_post.id] = result_post

        return posts


CHANNEL_NAME = "endchan"
CHANNEL_CLASS = EndchanChannel
CHANNEL_DESCRIPTION = "Endchan is a LynxChan-based imageboard with a range of user-created communities."
