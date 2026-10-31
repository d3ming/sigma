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
    """stated-rule: episode artwork and reusable show identity survive ingestion separately."""
    src = Source("s", "S", 1, rss=URL)
    direct = ingest.from_rss(src, NOW, 30, parsed=feedparser.parse(RSS, response_headers={"content-location": URL}))
    data = feedcache.load_feed(URL, get=Server(resp()), parse=feedcache.parse_bytes, directory=tmp_path)
    monkeypatch.setattr(feedcache, "load_feed", lambda url, **k: data)
    assert ingest.from_rss(src, NOW, 30) == direct and len(direct) == 2
    new = next(e for e in direct if e.title == "New one")
    assert new.duration == 3723 and new.audio_url.endswith("a.mp3") and new.transcript_urls[0]["url"] == "https://x/t.vtt"
    assert [e.image_url for e in direct] == ["https://show.example/episode.jpg", "https://show.example/show.jpg"]
    assert [e.show_image_url for e in direct] == ["https://show.example/show.jpg"] * 2
    written = fetch.write_episode(tmp_path, new, None, None)
    assert written["image_url"] == "https://show.example/episode.jpg" and written["show_image_url"] == "https://show.example/show.jpg"
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


def test_youtube_ingest_uses_verified_cached_channel_art_and_keeps_video_on_identity_mismatch(tmp_path, monkeypatch):
    """Stated rules: channel identity and date-window coverage. Outside-values: channelMetadataRenderer; captured Latent uploads at positions 10/13."""
    import json

    channel = "UC" + "a" * 22
    source = Source("channel", "Channel", 1, youtube=f"https://www.youtube.com/channel/{channel}/videos")
    video = {"id": "abcdefghijk", "title": "Interview", "timestamp": NOW.timestamp(), "duration": 3600,
             "thumbnail": "https://example.invalid/video.jpg"}
    monkeypatch.setattr(ingest, "_yt_json", lambda args: [video])
    metadata = {"externalId": channel, "avatar": {"thumbnails": [
        {"url": "https://example.invalid/avatar.jpg", "width": 900, "height": 900}]}}
    def response(url, **kwargs):
        assert url == f"https://www.youtube.com/channel/{channel}/about"
        return SimpleNamespace(raise_for_status=lambda: None,
                               text='<script>var ytInitialData = {"metadata":{"channelMetadataRenderer":' + json.dumps(metadata) + '}};</script>')
    monkeypatch.setattr(requests, "get", response)
    first = ingest.from_youtube(source, NOW, 7)
    assert [(e.image_url, e.show_image_url) for e in first] == [
        ("https://example.invalid/video.jpg", "https://example.invalid/avatar.jpg")]
    def unavailable(*args, **kwargs):
        raise requests.ConnectionError("offline")
    monkeypatch.setattr(requests, "get", unavailable)
    assert ingest.from_youtube(source, NOW, 7) == first
    monkeypatch.setenv("SIGMA_FEED_CACHE", str(tmp_path / "mismatch"))
    metadata["externalId"] = "UC" + "b" * 22
    monkeypatch.setattr(requests, "get", response)
    rejected = ingest.from_youtube(source, NOW, 7)
    assert [(e.id, e.show_image_url) for e in rejected] == [("yt:abcdefghijk", None)]
    assert not (tmp_path / "mismatch").exists()
    monkeypatch.setattr(requests, "get", unavailable)
    assert [(e.id, e.show_image_url) for e in ingest.from_youtube(source, NOW, 7)] == [("yt:abcdefghijk", None)]

    source.discover_youtube = True
    ids = [f"video{i:06d}" for i in range(1, 18)]
    ids[9], ids[12] = "ZOH8Q401vt0", "zlD-CkLVKtU"
    dates = {video_id: NOW.replace(day=20) for video_id in ids}
    dates[ids[14]] = NOW.replace(month=9, day=1)
    def ordered_uploads(args):
        if "--flat-playlist" in args:
            start, end = map(int, args[args.index("-I") + 1].split(":"))
            return [{"id": video_id} for video_id in ids[start - 1:end]]
        video_id = args[0].split("v=")[1]
        return [{"id": video_id, "title": "Full interview", "timestamp": dates[video_id].timestamp(), "duration": 3600}]
    monkeypatch.setattr(ingest, "_yt_json", ordered_uploads)
    found = ingest.from_youtube(source, NOW, 30)
    assert {"yt:ZOH8Q401vt0", "yt:zlD-CkLVKtU"} <= {episode.id for episode in found}
    assert [episode.id for episode in found] == ["yt:" + video_id for video_id in ids[:14]]
    source.discover_youtube = False
    assert [episode.id for episode in ingest.from_youtube(source, NOW, 30)] == ["yt:" + video_id for video_id in ids[:8]]
