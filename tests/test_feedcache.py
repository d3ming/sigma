from datetime import datetime, timezone
from types import SimpleNamespace

import feedparser
import pytest
import requests

from sigma import feedcache, fetch, ingest
from sigma.config import Source

RSS = b"""<?xml version="1.0"?><rss xmlns:podcast="https://podcastindex.org/namespace/1.0"
xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" version="2.0"><channel><link>https://show.example</link>
<image><url>https://show.example/show.jpg</url></image>
<item><guid>ep-new</guid><title> New one </title><link>/new</link><pubDate>Mon, 19 Oct 2026 08:00:00 GMT</pubDate>
<itunes:duration>01:02:03</itunes:duration><description>Hello</description>
<itunes:image href="https://show.example/episode.jpg"/>
<enclosure url="https://cdn.example/a.mp3" type="audio/mpeg" length="1"/>
<podcast:transcript url="https://x/t.vtt" type="text/vtt"/></item>
<item><guid>ep-old</guid><title>Old one</title><pubDate>Mon, 05 Oct 2026 08:00:00 GMT</pubDate></item>
</channel></rss>"""
NOW = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
URL = "https://feed.example/rss"


def resp(status=200, body=RSS, **headers):
    return SimpleNamespace(status_code=status, content=body, headers=headers, url=URL)


class Server:
    """Records requests; replays the queued responses (an Exception instance is raised)."""
    def __init__(self, *queue):
        self.queue, self.sent = list(queue), []

    def __call__(self, url, headers=None, timeout=None):
        self.sent.append(headers)
        r = self.queue.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class Parser:
    def __init__(self):
        self.calls = 0

    def __call__(self, body, headers=None):
        self.calls += 1
        return feedcache.parse_bytes(body, headers)


def test_feeds_are_fetched_conditionally_and_parsed_only_when_they_changed(tmp_path, monkeypatch):
    srv, parse = Server(resp(etag='"v1"', **{"last-modified": "Mon, 19 Oct 2026 09:00:00 GMT"}), resp(304, b"")), Parser()
    first = feedcache.load_feed(URL, get=srv, parse=parse, directory=tmp_path)
    assert feedcache.load_feed(URL, get=srv, parse=parse, directory=tmp_path) == first and parse.calls == 1  # a 304 reuses the cache
    assert srv.sent[1]["If-None-Match"] == '"v1"' and srv.sent[1]["If-Modified-Since"].startswith("Mon, 19 Oct")
    assert "If-None-Match" not in srv.sent[0]
    other = tmp_path / "other"  # a server with no validators: an identical body is not parsed again, a changed one is
    srv, parse = Server(resp(), resp()), Parser()
    feedcache.load_feed(URL, get=srv, parse=parse, directory=other)
    feedcache.load_feed(URL, get=srv, parse=parse, directory=other)
    assert parse.calls == 1
    srv.queue.append(resp(body=RSS.replace(b"Old one", b"Older one")))
    assert feedcache.load_feed(URL, get=srv, parse=parse, directory=other)["entries"][1]["title"] == "Older one" and parse.calls == 2
    old = tmp_path / "old"  # a cache past MAX_AGE is not trusted for validators
    srv = Server(resp(etag='"v1"'), resp(etag='"v2"'))
    feedcache.load_feed(URL, get=srv, parse=Parser(), directory=old)
    monkeypatch.setattr(feedcache, "MAX_AGE", -1)
    feedcache.load_feed(URL, get=srv, parse=Parser(), directory=old)
    assert "If-None-Match" not in srv.sent[1]


def test_a_feed_that_fails_is_an_error_never_the_cached_copy(tmp_path):
    for n, failure in enumerate([requests.ConnectionError("down"), resp(500, b"")]):
        srv = Server(resp(etag='"v1"'), failure)
        feedcache.load_feed(URL, get=srv, parse=Parser(), directory=tmp_path / str(n))
        with pytest.raises((requests.RequestException, ValueError)):
            feedcache.load_feed(URL, get=srv, parse=Parser(), directory=tmp_path / str(n))
    with pytest.raises(ValueError):  # not a feed at all
        feedcache.load_feed(URL, get=Server(resp(body=b"<html>nope")), parse=Parser(), directory=tmp_path / "html")
    with pytest.raises(ValueError):  # "not modified" with nothing cached is not an empty feed
        feedcache.load_feed(URL, get=Server(resp(304, b"")), parse=Parser(), directory=tmp_path / "empty")


def test_cached_pool_and_direct_parsing_give_the_same_episodes(tmp_path, monkeypatch):
    """stated-rule: publisher episode artwork wins; show artwork survives when the episode has none."""
    src = Source("s", "S", 1, rss=URL)
    direct = ingest.from_rss(src, NOW, 30, parsed=feedparser.parse(RSS, response_headers={"content-location": URL}))
    data = feedcache.load_feed(URL, get=Server(resp()), parse=feedcache.parse_bytes, directory=tmp_path)
    monkeypatch.setattr(feedcache, "load_feed", lambda url, **k: data)
    assert ingest.from_rss(src, NOW, 30) == direct and len(direct) == 2
    new = next(e for e in direct if e.title == "New one")
    assert new.duration == 3723 and new.audio_url.endswith("a.mp3") and new.transcript_urls[0]["url"] == "https://x/t.vtt"
    assert [e.image_url for e in direct] == ["https://show.example/episode.jpg", "https://show.example/show.jpg"]
    assert fetch.write_episode(tmp_path, new, None, None)["image_url"] == "https://show.example/episode.jpg"
    got = feedcache.pool_parse(RSS, {"content-location": URL})  # the worker-process path
    assert got == feedcache.parse_bytes(RSS, {"content-location": URL}) and len(got["entries"]) == 2


def test_the_process_pool_is_created_once_across_threads(monkeypatch):
    import threading
    import time as _t

    made = []

    class FakePool:
        def __init__(self, n):
            _t.sleep(0.01)  # widen the race window
            made.append(self)

        def shutdown(self, **kw):
            pass

    monkeypatch.setattr(feedcache, "_pool", None)
    monkeypatch.setattr(feedcache, "ProcessPoolExecutor", FakePool)
    ts = [threading.Thread(target=feedcache._get_pool) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(made) == 1
