"""Where a reader can listen: the link `sigma links` gives each selected episode, the links the published files and site carry,
and the show-links file. Real title pairs from past weeks; every network call below is a fake."""
import copy
import hashlib
import json
import re
import subprocess

import pytest
import yaml

from sigma import links, published, ranked, report, showlinks, site
from sigma.digest import render, show_line
from sigma.ranked import RankedError
from tests.helpers import REPORT

APPLE = "https://podcasts.apple.com/us/podcast/plain-english/id1594471023"
SHOW_APPLE = "https://podcasts.apple.com/us/podcast/the-a16z-show/id1594471024"
TITLE = "The AI Story Wall Street Doesn't Want to Hear"


def ap(name, date, i, **kw):
    return {"wrapperType": "podcastEpisode", "trackName": name, "releaseDate": f"{date}T08:00:00Z",
            "trackViewUrl": f"https://podcasts.apple.com/us/podcast/x/id1594471023?i={i}&uo=4", **kw}


GUID = "tag:example.com,2026:ep-9"
LOOKUP = {"results": [
    {"wrapperType": "track", "collectionName": "Plain English"},
    ap(TITLE, "2026-10-23", 111), ap(TITLE, "2026-08-01", 222),  # the same title two months earlier is another episode
    ap("Something else entirely", "2026-10-23", 333),
    ap("Sundar Pichai, Part 2", "2026-10-23", 2),
    ap("Retitled for Apple", "2026-10-20", 7, episodeGuid=GUID),
    ap("Daily Briefing", "2026-10-25", 25), ap("Daily Briefing", "2026-10-24", 24),
    ap("Renamed", "2026-10-20", 5, episodeUrl="https://cdn.example.com/show/ep5.mp3?x=1"),
]}
JASSY = {"title": "Amazon CEO Andy Jassy on the $220 Billion AI Buildout", "show": "The a16z Show", "published": "2026-10-23"}
JASSY_V = "Amazon CEO Andy Jassy: $220 Billion, Still Can't Meet AI Demand"
EP = {"title": "The New Apex Predator: CrowdStrike CEO George Kurtz on Adversaries", "show": "No Priors",
      "published": "2026-10-22", "guests": [{"name": "George Kurtz", "role": "CEO"}, {"name": "Sarah Guo", "role": "host"}]}


def sel(eid, show, title, published="2026-10-23", **kw):
    return {"episode_id": eid, "show": show, "title": title, "published": published, **kw}


def test_fill_gives_each_selected_episode_its_best_listen_link(tmp_path):
    """`sigma links`: a verified YouTube video when there is one; else an Apple episode page matched on the title and date, or on
    the feed's own identity; else the page the feed gave; the show's Apple page only when nothing better exists."""
    run = tmp_path / "run"
    run.mkdir()
    audio_eid = "rss:" + hashlib.sha1(GUID.encode()).hexdigest()[:16]
    eps = [
        sel("home", "Plain English", TITLE, url="https://www.theringer.com/"),  # the show's homepage is not an episode page
        sel("good", "OK Show", TITLE, url="https://ok.example/episodes/1"),
        sel("nothing", "Plain English", "No such episode", url=""),
        sel("part1", "Plain English", "Sundar Pichai, Part 1"),  # only Part 2 is on Apple
        sel(audio_eid, "Plain English", "Original title", url=""),
        sel("closest", "Plain English", "Daily Briefing", url=""),
        sel("enclosure", "Plain English", "Original", url="", audio_url="https://dts.podtrac.com/redirect.mp3/cdn.example.com/show/ep5.mp3?source=feed"),
        sel("unverified", "No Priors", EP["title"], "2026-10-22", url="https://x.com/ep", youtube_url="https://youtu.be/abcdefghijk"),
        sel("notes", "The a16z Show", JASSY["title"], url="https://traffic.megaphone.fm/x.mp3",
            description="Prev: https://youtu.be/AAAAAAAAAAA Watch: https://www.youtube.com/watch?v=BBBBBBBBBBB&t=1"),
        sel("channel", "Chan Show", JASSY["title"], url=""),
    ]
    (run / "selected.json").write_text(json.dumps({"episodes": eps}))
    (run / "manifest.json").write_text(json.dumps({"episodes": [{k: e[k] for k in ("episode_id", "title", "audio_url") if k in e} for e in eps]}))
    sl = tmp_path / "show_links.yaml"
    sl.write_text(yaml.safe_dump({"pe": {"name": "Plain English", "site": "https://www.theringer.com/", "youtube": "", "apple": APPLE, "spotify": ""},
                                  "ok": {"name": "OK Show", "site": "", "youtube": "", "apple": APPLE, "spotify": ""}}))
    src = tmp_path / "sources.yaml"
    src.write_text(yaml.safe_dump({"sources": [{"id": "chan", "name": "Chan Show", "rss": "https://feed/c", "youtube_channel_id": "UCchan"}]}))

    def get(url):
        return LOOKUP if "lookup" in url else {"results": []}

    def fetch(url, **k):
        if "oembed" in url and "AAAAAAAAAAA" in url:
            return json.dumps({"title": "Other episode entirely", "author_name": "Show"})
        if "oembed" in url and "BBBBBBBBBBB" in url:
            return json.dumps({"title": JASSY["title"], "author_name": "The a16z Show"})
        if "oembed" in url:
            return json.dumps({"title": "unrelated", "author_name": "Someone"})
        if "videos.xml" in url:
            return ("<feed><entry><yt:videoId>zzzzzzzzzzz</yt:videoId><title>Other episode</title><published>2026-10-23</published></entry>"
                    "<entry><yt:videoId>ccccccccccc</yt:videoId><title>Amazon CEO Andy Jassy: $220 Billion, Still Can&#39;t Meet AI Demand</title>"
                    "<published>2026-10-23T09:00:00+00:00</published></entry></feed>")
        raise OSError("no network")

    out = links.fill(run, src, get=get, fetch=fetch, show_links=sl)
    listen = {k: v[1] for k, v in out.items()}
    assert listen["home"].endswith("?i=111") and "&uo" not in listen["home"]
    assert listen["good"] == "https://ok.example/episodes/1"
    assert listen["nothing"] == APPLE and listen["part1"] == APPLE  # the show's page, not another part's page
    assert listen[audio_eid].endswith("?i=7") and listen["enclosure"].endswith("?i=5") and listen["closest"].endswith("?i=24")
    assert out["unverified"] == (None, "https://x.com/ep")
    assert out["notes"][0] == "https://www.youtube.com/watch?v=BBBBBBBBBBB"  # the note's first link is another episode
    assert out["channel"][0] == "https://www.youtube.com/watch?v=ccccccccccc"
    chosen = {e["episode_id"]: e for e in json.loads((run / "selected.json").read_text())["episodes"]}
    assert "youtube_url" not in chosen["unverified"] and chosen["notes"]["youtube_url"].endswith("BBBBBBBBBBB")
    rows = {e["episode_id"]: e for e in json.loads((run / "manifest.json").read_text())["episodes"]}
    assert rows["home"]["listen_url"] == chosen["home"]["listen_url"] and rows["channel"]["youtube_url"].endswith("ccccccccccc")
    # a show whose Apple page cannot be read still gets its own page link
    again = links.fill(run, src, get=lambda u: (_ for _ in ()).throw(OSError("down")), fetch=lambda u, **k: (_ for _ in ()).throw(OSError("down")),
                       show_links=sl)
    assert again["nothing"][1] == APPLE


def test_a_youtube_video_must_look_like_the_episode_and_be_from_its_week():
    assert links.yt_matches(EP, "The New Apex Predator: CrowdStrike CEO George Kurtz on Adversaries Armed With AI Agents", "x", "2026-10-22T10:00:00Z")
    assert not links.yt_matches(EP, "The New Apex Predator: CrowdStrike CEO George Kurtz on Adversaries", "x", "2026-09-01")  # date far
    assert links.yt_matches(EP, "George Kurtz on AI security", "No Priors: AI, Machine Learning", None)  # guest + own channel
    assert not links.yt_matches(EP, "George Kurtz on AI security", "CNBC Television", None)  # guest on another channel
    assert not links.yt_matches(EP, "Sarah Guo on startups", "No Priors", None)  # a host's name doesn't count
    assert links.similar(JASSY["title"], JASSY_V) < 0.75  # YouTube retitled it: similarity alone would miss it
    assert links.yt_matches(JASSY, JASSY_V, "a16z", "2026-10-23")
    assert not links.yt_matches(JASSY, JASSY_V, "a16z", None)  # no date
    assert not links.yt_matches(JASSY, JASSY_V, "a16z", "2026-10-13")  # right names, ten days apart
    assert not links.yt_matches(JASSY, JASSY_V, "CNBC Television", "2026-10-23")  # another channel
    assert not links.yt_matches(JASSY, "Microsoft CEO Satya Nadella: $220 Billion, Still Can't Meet AI Demand", "a16z", "2026-10-23")  # another guest
    assert not links.yt_matches({**JASSY, "title": "The New Era of Chips"}, "The New Rules of Software", "a16z", "2026-10-23")  # "The New" is no name
    robots = {"title": "why robotics startups are finally raising serious money", "show": "The a16z Show", "published": "2026-10-23"}
    assert links.yt_matches(robots, "Robotics startups raising serious capital", "a16z", "2026-10-23")  # four distinctive words
    assert not links.yt_matches(robots, "Robotics startups and chips", "a16z", "2026-10-23")  # two
    assert not links.yt_matches(JASSY, "Amazon CEO Andy Jassy clip: $220 Billion AI demand", "a16z", "2026-10-23")  # a clip
    bloomberg = {"title": "Wall Street bets on rate cuts and tech earnings", "show": "Bloomberg Tech", "published": "2026-10-20"}
    assert not links.yt_matches(bloomberg, "Wall Street waits on Fed", "Bloomberg Tech", "2026-10-20")  # a place name is not a guest
    fetch = lambda url, **k: json.dumps({"title": JASSY_V, "author_name": "a16z"})  # noqa: E731
    u = "https://youtu.be/abcdefghijk"
    assert links.yt_verify(JASSY, u, fetch=fetch) is None  # no date known: stay strict
    assert links.yt_verify(JASSY, u, "2026-10-23", fetch=fetch) == "https://www.youtube.com/watch?v=abcdefghijk"
    assert links.yt_verify({**JASSY, "youtube_published": "2026-10-23"}, u, fetch=fetch) is None  # that date describes the agent's URL, not this video
    xml = ("<feed><entry><yt:videoId>zzzzzzzzzzz</yt:videoId><title>Other episode</title><published>2026-10-23</published></entry></feed>")
    assert links.yt_channel_rss(JASSY, "UC1", fetch=lambda u, **k: xml) is None


def test_a_retitled_video_on_the_shows_own_channel_matches_by_day_and_length(monkeypatch):
    """the podcast episode (761 s, Oct 20) and the YouTube video on the same channel (12:42, Oct 20)
    carry different titles. Other cases are the rule's stated limits: one day, 5% or 60 s, a length on both sides."""
    csi = {"title": "CoreWeave Bond Crash: Why CRWV & Neocloud Stocks Are Tumbling", "show": "Chip Stock Investor",
           "published": "2026-10-20", "duration": "761"}
    video = "CoreWeave Bonds Hit 15% Yield: Are Neoclouds In Trouble?"
    assert links.yt_matches(csi, video, "Chip Stock Investor", "2026-10-20", duration=762)
    assert links.yt_matches(csi, video, "Chip Stock Investor", "2026-10-21", duration=762)
    assert not links.yt_matches(csi, video, "Chip Stock Investor", "2026-10-22", duration=762)  # two days
    assert not links.yt_matches(csi, video, "Chip Stock Investor", "2026-10-20", duration=1500)  # another video of the day
    assert not links.yt_matches(csi, video, "Chip Stock Investor", "2026-10-20")  # no length: the channel and day alone prove nothing
    assert not links.yt_matches(csi, video, "CNBC Television", "2026-10-20", duration=762)  # not the show's channel
    # listings: the show's /streams tab is read too, and a listed length stands in for the title
    calls = []

    def run(cmd):
        if "--skip-download" in cmd:
            return "20261020\n"
        calls.append(cmd[-1])
        return "u4ajXt_hO9A\t" + video + "\tNA\tNA\t762\n" if cmd[-1].endswith("/streams") else "aaaaaaaaaaa\tAn older one\tNA\tNA\t3000\n"

    fetch = oembed({"u4ajXt_hO9A": (video, "Chip Stock Investor"), "aaaaaaaaaaa": ("An older one", "Chip Stock Investor")})
    assert links.yt_channel_uploads(csi, "https://youtube.com/@ChipStockInvestor", fetch, run) == "https://www.youtube.com/watch?v=u4ajXt_hO9A"
    assert [c.rsplit("/", 1)[-1] for c in calls][-2:] == ["videos", "streams"]
    # a channel without a streams tab is an empty list, not a block that counts toward giving up on yt-dlp
    monkeypatch.setitem(links._YTDLP, "fails", 0)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(
        subprocess.CalledProcessError(1, "yt-dlp", stderr="ERROR: [youtube:tab] @x: This channel does not have a streams tab")))
    assert links.ytdlp_run(["yt-dlp"]) == "" and links._YTDLP["fails"] == 0


LOTS = {"title": "The Forgotten Godmother of Economic Literature", "show": "Odd Lots", "published": "2026-10-23"}
ALTMAN = {"title": "Sam Altman: RSI, AI Consciousness, OpenAI's New Hardware, Compute, and more!", "show": "Forward Future Interviews",
          "published": "2026-10-21"}
ELON = {"title": 'Elon Musk: "Humans Won\'t Be in Control" When AI Becomes Smarter Than Us', "show": "The Builders", "published": "2026-10-20"}
ELON_TW = "「有幾次我想過，也許佩吉是對的」數位智慧多到一百萬倍時，人類還管得住 AI 嗎？｜馬斯克×《賈伯斯傳》作者艾薩克森"


def oembed(titles):
    def fetch(url, **kw):
        vid = re.search(r"v=([\w-]{11})", url).group(1)
        t, ch = titles[vid]
        return json.dumps({"title": t, "author_name": ch})
    return fetch


def test_youtube_is_searched_by_channel_then_by_title_and_yt_dlp_is_given_up_on(monkeypatch):
    calls = []

    def run(cmd):
        calls.append(cmd[-1])
        if "--skip-download" in cmd:
            return "20261023\n"
        if cmd[-1].endswith("/search?query=The+Forgotten+Godmother+of+Economic+Literature"):
            return "aaaaaaaaaaa\tAn older Odd Lots\tBloomberg Podcasts\tNA\n"
        return "8_PhNY5j81g\tThe Forgotten Godmother of Economic Literature | Odd Lots\tBloomberg Podcasts\tNA\n"

    fetch = oembed({"8_PhNY5j81g": ("The Forgotten Godmother of Economic Literature | Odd Lots", "Bloomberg Podcasts"),
                    "aaaaaaaaaaa": ("An older Odd Lots", "Bloomberg Podcasts")})
    u = links.yt_channel_uploads(LOTS, "https://www.youtube.com/channel/UChF5O40UBqAc82I7-i5ig6A/videos", fetch, run)
    assert u == "https://www.youtube.com/watch?v=8_PhNY5j81g"
    assert calls[0].endswith("/channel/UChF5O40UBqAc82I7-i5ig6A/search?query=The+Forgotten+Godmother+of+Economic+Literature")
    assert calls[1].endswith("/channel/UChF5O40UBqAc82I7-i5ig6A/videos")
    assert links.yt_channel_uploads({**LOTS, "published": "2026-09-01"}, "https://www.youtube.com/@x", fetch, run) is None  # a month earlier: another episode
    assert links.yt_channel_uploads(LOTS, "https://example.com/not-youtube", fetch, run) is None
    seen = []

    def search(cmd):
        seen.append(cmd[-1])
        if "--skip-download" in cmd:
            return "20261021\n"
        if cmd[-1].startswith("ytsearch5:Forward Future"):
            return "zzzzzzzzzzz\tUnrelated\tSomeone\tNA\n"
        return "3gXLmy7DK_4\t" + ALTMAN["title"] + "\tMatthew Berman\tNA\n"

    fetch = oembed({"zzzzzzzzzzz": ("Unrelated", "Someone"), "3gXLmy7DK_4": (ALTMAN["title"], "Matthew Berman")})
    assert links.yt_ytsearch(ALTMAN, fetch, search) == "https://www.youtube.com/watch?v=3gXLmy7DK_4"
    assert seen[0].startswith("ytsearch5:Forward Future Interviews") and seen[1] == "ytsearch5:" + ALTMAN["title"]  # retried with the title alone
    only_a_commentary = lambda cmd: "b1WJAJJsbV0\t" + ELON_TW + "\t科技立委葛如鈞\tNA\n"  # noqa: E731
    assert links.yt_ytsearch(ELON, oembed({"b1WJAJJsbV0": (ELON_TW, "科技立委葛如鈞")}), only_a_commentary) is None
    monkeypatch.setitem(links._YTDLP, "fails", 0)
    n = []

    def boom(*a, **k):
        n.append(1)
        raise subprocess.CalledProcessError(1, "yt-dlp")

    monkeypatch.setattr(subprocess, "run", boom)
    for _ in range(5):
        with pytest.raises(Exception):
            links.ytdlp_run(["yt-dlp"])
    assert len(n) == 3  # YouTube blocks server IPs: the 4th and 5th calls never reached yt-dlp


EMBED = ('<script id="__NEXT_DATA__" type="application/json">' + json.dumps({"props": {"pageProps": {"state": {"data": {"entity": {
    "title": ALTMAN["title"], "releaseDate": {"isoString": "2026-10-21T12:00:00Z"}}}}}}}) + "</script>")
SHOW_PAGE = ('<a href="/episode/1WAzJv8l0Z9tbMJU0WZM4x"><h4><span aria-label="New episode"></span>' + ALTMAN["title"] +
             '</h4></a><a href="/episode/7dRKecSh7AvdmcAazu1MDw"><h4>Tibo Interview</h4></a>')


def spotify_fake(url, **kw):
    if "/embed/episode/1WAzJv8l0Z9tbMJU0WZM4x" in url:
        return EMBED
    if "/show/" in url:
        return SHOW_PAGE
    raise OSError("not found")


def test_spotify_and_apple_episode_pages_are_checked_and_one_failure_costs_only_that_link(monkeypatch):
    show = "https://open.spotify.com/show/0Dh9ThY7AsAgAbIqAqFLug"
    assert links.spotify_episode(ALTMAN, show, spotify_fake) == "https://open.spotify.com/episode/1WAzJv8l0Z9tbMJU0WZM4x"
    assert links.spotify_episode({**ALTMAN, "published": "2026-10-01"}, show, spotify_fake) is None  # right title, wrong week
    assert links.spotify_episode({**ALTMAN, "title": "A different interview"}, show, spotify_fake) is None
    assert links.spotify_episode(ALTMAN, None, spotify_fake) is None  # no show page to read, nothing in the notes
    notes = {**ALTMAN, "description": "Listen: https://open.spotify.com/episode/1WAzJv8l0Z9tbMJU0WZM4x?si=abc"}
    assert links.spotify_episode(notes, None, spotify_fake).endswith("1WAzJv8l0Z9tbMJU0WZM4x")  # a link in the notes is still verified
    assert links.spotify_episode({**ALTMAN, "description": "https://open.spotify.com/episode/AAAAAAAAAAAAAAAAAAAAAA"}, None, spotify_fake) is None
    ep = {"title": "Meta Doubles Down on AI Spending, Plans New Class C Shares", "published": "2026-10-22",
          "url": "https://podcasts.apple.com/us/podcast/meta-doubles/id1611767434?i=1000797664748&uo=4"}
    assert links.apple_episode_link(ep, None) == "https://podcasts.apple.com/us/podcast/meta-doubles/id1611767434?i=1000797664748"
    show_only = {**ep, "url": "https://podcasts.apple.com/us/podcast/bloomberg-tech/id1611767434"}
    assert links.apple_episode_link(show_only, None) is None  # no ?i=: that is the show, not the episode
    assert links.apple_episode_link({**ep, "url": "https://x.com/e"}, "https://podcasts.apple.com/us/podcast/x/id1611767434", get=lambda u: {"results": []}) is None
    yt = "https://www.youtube.com/watch?v=3gXLmy7DK_4"

    def fake_youtube(ep, channel_id, fetch, ytsearch, run, channel_url):
        if ep["episode_id"] == "b":
            raise OSError("blocked")
        return yt if ep["episode_id"] == "a" else None

    monkeypatch.setattr(links, "youtube", fake_youtube)
    shows = {"forward future interviews": {"youtube": "https://www.youtube.com/channel/UCberman", "spotify": "https://open.spotify.com/show/0Dh9ThY7AsAgAbIqAqFLug"},
             "bloomberg tech": {"spotify": "https://open.spotify.com/show/showonly"}}
    rows = [{**ALTMAN, "episode_id": "a", "url": "https://podcasts.apple.com/us/podcast/x/id9?i=77&uo=4"},
            {"episode_id": "b", "title": "Meta Doubles Down", "show": "Bloomberg Tech", "published": "2026-10-22"},
            {"episode_id": "c", "title": "Nothing anywhere", "show": "Unlisted Show", "published": "2026-10-22"}]
    out = links.listen_links(rows, shows, {"forward future interviews": {"youtube_channel_id": "UCsrc"}}, get=lambda u: {}, spotify_fetch=spotify_fake)
    assert out["a"] == {"youtube_url": yt, "apple_url": "https://podcasts.apple.com/us/podcast/x/id9?i=77",
                        "spotify_url": "https://open.spotify.com/episode/1WAzJv8l0Z9tbMJU0WZM4x", "spotify_kind": "episode"}
    assert out["b"] == {"spotify_url": "https://open.spotify.com/show/showonly", "spotify_kind": "show"}  # YouTube failed; the others stand
    assert "c" not in out  # nothing found: no link fields at all


def make_run(tmp_path):
    run = tmp_path / "runs" / "weekly"
    run.mkdir(parents=True)
    (run / "a.md").write_text("## Transcript\n\n[0:01:01] Capacity demand is running ahead of current supply.\n")
    (run / "b.md").write_text("## Transcript\n\n[0:01:01] Capacity demand is running ahead of current supply.\n")
    (run / "manifest.json").write_text(json.dumps({"episodes": [
        {"episode_id": "rss:a", "title": "A", "source": "Show A", "published": "2026-10-20", "tier": 1, "file": "a.md",
         "has_transcript": True, "description": "private show notes", "audio_url": "https://x/a.mp3", "youtube_id": "abcdefghijk"},
        {"episode_id": "rss:b", "title": "B", "source": "Show B", "published": "2026-10-21", "tier": 1,
         "file": "b.md", "has_transcript": True, "description": "notes"},
        {"episode_id": "rss:z", "title": "Z (not in the ranking)", "source": "Show Z", "published": "2026-10-21"}]}))
    (run / "ranked.json").write_text(json.dumps({"week_of": "2026-10-17", "run_dir": str(run), "ranked_by": "test", "episodes": [
        {"rank": 1, "episode_id": "rss:a", "title": "rss:a", "url": "https://example.com/a", "source": "Show A", "tier": 1,
         "published": "2026-10-20", "score": 7, "reason": "reason", "claims": [
             {"claim": "Capacity demand runs ahead of supply.", "speaker": "CEO", "timestamp": 61, "ticker": ["nvda"], "novelty": 1, "verifiable": 1}]},
        {"rank": 2, "episode_id": "rss:b", "title": "rss:b", "url": "https://example.com/b", "source": "Show B", "tier": 1,
         "published": "2026-10-21", "score": 7, "reason": "reason", "claims": [
             {"claim": "Capacity demand runs ahead of supply.", "speaker": "CEO", "timestamp": 61, "ticker": ["nvda"], "novelty": 1, "verifiable": 1}]}]}))
    return run


FULL = {"youtube_url": "https://www.youtube.com/watch?v=abcdefghijk", "apple_url": "https://podcasts.apple.com/us/podcast/x/id1?i=2",
        "spotify_url": "https://open.spotify.com/episode/1WAzJv8l0Z9tbMJU0WZM4x", "spotify_kind": "episode"}


def names(h):
    return re.findall(r'<a class="lk [a-z]+"[^>]*aria-label="([^"]+)"', h)


def build_site(tmp_path, meta):
    d = tmp_path / "published" / "2026-10-17-weekly"
    d.mkdir(parents=True)
    ep = {"episode_id": "rss:a", "title": "Jassy on AWS", "source": "Show A", "tier": 1, "published": "2026-10-20", "score": 8,
          "url": "https://example.com/e", "rank": 1, "claims": [{"claim": "Capacity is sold out", "speaker": "Andy Jassy (Amazon CEO)",
                                                                  "timestamp": 90, "ticker": ["AMZN"]}]}
    (d / "ranked.json").write_text(json.dumps({"week_of": "2026-10-17", "episodes": [ep]}))
    (d / "episodes.json").write_text(json.dumps([{"episode_id": "rss:a", "title": "Jassy on AWS", "source": "Show A", **meta}]))
    row = {"episode_id": "rss:a", "title": "Jassy on AWS", "show": "Show A", "published": "2026-10-20", "date": "2026-10-20", "run": d.name,
           "speaker": "Andy Jassy (Amazon CEO)", "timestamp": 90, "text": "Capacity is sold out", "tickers": ["AMZN"],
           "url": "https://example.com/e", "youtube_url": None, "link": "https://example.com/e"}
    (d / "claims.jsonl").write_text(json.dumps(row) + "\n")
    out = tmp_path / "dist"
    site.build(tmp_path / "published", out)
    return out


def test_published_files_and_the_site_carry_the_links_and_nothing_private(tmp_path):
    asked = []

    def resolver(rows):
        asked.extend(r["episode_id"] for r in rows)
        return {"rss:b": {"youtube_url": "https://www.youtube.com/watch?v=bbbbbbbbbbb", "apple_url": "https://podcasts.apple.com/us/podcast/b/id1?i=2",
                          "spotify_url": "https://open.spotify.com/show/xyz", "spotify_kind": "show", "junk": "dropped"},
                "rss:a": {"apple_url": "https://podcasts.apple.com/us/podcast/a/id1?i=1"}}

    run, root = make_run(tmp_path), tmp_path / "published"
    dest, _ = published.export(run, root=root, resolver=resolver)
    assert sorted(asked) == ["rss:a", "rss:b"]  # the episode outside the ranking is never looked up
    # stated rule: every episode whose claims get published is looked up; a daily's claims come from scores.json
    (run / "scores.json").write_text(json.dumps({"episodes": [{"episode_id": "rss:z", "claims": [{"claim": "c"}]},
                                                              {"episode_id": "rss:q", "claims": []}]}))
    assert published.listed_ids(run) == ["rss:a", "rss:b", "rss:z"]
    (run / "scores.json").unlink()
    eps = {e["episode_id"]: e for e in json.loads((dest / "episodes.json").read_text())}
    assert eps["rss:a"]["youtube_url"] == "https://www.youtube.com/watch?v=abcdefghijk"  # derived from youtube_id
    assert eps["rss:a"]["apple_url"].endswith("?i=1") and "spotify_url" not in eps["rss:a"]
    assert eps["rss:b"]["spotify_kind"] == "show" and "junk" not in eps["rss:b"]
    assert not any(k in e for e in eps.values() for k in ("description", "audio_url", "file"))
    assert "private" not in (dest / "episodes.json").read_text() and "/Users/" not in (dest / "episodes.json").read_text()
    claims = [json.loads(line) for line in (dest / "claims.jsonl").read_text().splitlines()]
    b = next(c for c in claims if c["episode_id"] == "rss:b")
    assert b["youtube_url"] == "https://www.youtube.com/watch?v=bbbbbbbbbbb" and b["link"].endswith("bbbbbbbbbbb&t=61s")
    before = {p.name: p.read_bytes() for p in dest.iterdir() if p.is_file()}
    manifest = json.loads((run / "manifest.json").read_text())
    for title in ("our portfolio allocations", "our\nportfolio: NVDA 25%", "our\tportfolio: NVDA 25%",
                  "-----BEGIN PRIVATE KEY-----", "sk_test_0123456789abcdef"):
        manifest["episodes"][0]["title"] = title
        (run / "manifest.json").write_text(json.dumps(manifest))
        with pytest.raises(ValueError, match=r"(episodes\.json|claims\.jsonl) looks private"):
            published.export(run, root=root, resolver=False)
        assert {p.name: p.read_bytes() for p in dest.iterdir() if p.is_file()} == before
    ranked_data = json.loads((run / "ranked.json").read_text())
    ranked_data["episodes"][0]["reason"] = "our\nportfolio: NVDA 25%"
    with pytest.raises(RankedError, match="private text"):
        ranked.validate(ranked_data)
    (run / "ranked.json").write_text(json.dumps(ranked_data))
    with pytest.raises(ValueError, match="ranked.json looks private"):
        published.export(run, root=root, resolver=False)
    assert {p.name: p.read_bytes() for p in dest.iterdir() if p.is_file()} == before
    ranked_data["episodes"][0]["reason"] = "reason"
    ranked_data["DATABASE_PASSWORD"] = "synthetic-example-123"
    (run / "ranked.json").write_text(json.dumps(ranked_data))
    with pytest.raises(ValueError, match="ranked.json looks private") as exc:
        published.export(run, root=root, resolver=False)
    assert "DATABASE_PASSWORD" not in str(exc.value) and "synthetic-example-123" not in str(exc.value)
    assert {p.name: p.read_bytes() for p in dest.iterdir() if p.is_file()} == before
    ranked_data.pop("DATABASE_PASSWORD")
    (run / "ranked.json").write_text(json.dumps(ranked_data))
    manifest["episodes"][0]["title"] = "A"
    (run / "manifest.json").write_text(json.dumps(manifest))
    # influencer scores are published like scores.json, under the same privacy check, and the episode's style travels with it
    manifest["episodes"].append({"episode_id": "yt:i", "title": "I", "source": "Show I", "published": "2026-10-21", "tier": 2, "style": "influencer"})
    (run / "manifest.json").write_text(json.dumps(manifest))
    inf = {"week_of": "2026-10-17", "run_dir": str(run), "ranked_by": "test", "rubric": 1,
           "episodes": [{"rank": 1, "episode_id": "yt:i", "title": "I", "url": "https://example.com/i", "source": "Show I", "tier": 2,
                         "published": "2026-10-21", "score": 7, "reason": "Levels on one name", "claims": []}]}
    (run / "scores-influencer.json").write_text(json.dumps(inf))
    dest, _ = published.export(run, root=root, resolver=False)
    assert json.loads((dest / "scores-influencer.json").read_text()) == inf
    assert {e["episode_id"]: e.get("style") for e in json.loads((dest / "episodes.json").read_text())}["yt:i"] == "influencer"
    (run / "scores-influencer.json").write_text(json.dumps({**inf, "notes": "reflects our holdings of the name"}))
    with pytest.raises(ValueError, match="scores-influencer.json looks private"):
        published.export(run, root=root, resolver=False)
    (run / "scores-influencer.json").unlink()
    # a lookup that fails keeps the links an earlier export found; switching lookups off does too
    def down(rows):
        raise OSError("network down")

    dest, _ = published.export(run, root=root, resolver=down)
    assert {e["episode_id"]: e for e in json.loads((dest / "episodes.json").read_text())}["rss:b"]["apple_url"].endswith("?i=2")
    dest, _ = published.export(run, root=root, resolver=False)
    assert json.loads((dest / "episodes.json").read_text())[1]["apple_url"].endswith("?i=2")
    # stated rule: stance labels are made after an export, so a re-export must keep them (public data nobody can regenerate)
    (dest / "stances.jsonl").write_text('{"key": "c-0123456789ab", "labels": []}\n')
    dest, _ = published.export(run, root=root, resolver=False)
    assert (dest / "stances.jsonl").read_text() == '{"key": "c-0123456789ab", "labels": []}\n'
    before = {p.name: p.read_bytes() for p in dest.iterdir() if p.is_file()}
    (dest / "stances.jsonl").write_text('{"note": "our portfolio allocations"}\n')
    before_refusal = {p.name: p.read_bytes() for p in dest.iterdir() if p.is_file()}
    with pytest.raises(ValueError, match="stances.jsonl looks private"):
        published.export(run, root=root, resolver=False)
    assert {p.name: p.read_bytes() for p in dest.iterdir() if p.is_file()} == before_refusal
    (dest / "stances.jsonl").write_bytes(before["stances.jsonl"])
    # the site: icons in a fixed order, only the ones that exist, never a javascript: link; the Markdown and JSON carry the same links
    assert names(site.listen_icons(FULL)) == ["Watch on YouTube", "Listen on Apple Podcasts", "Listen on Spotify"]
    assert names(site.listen_icons({"apple_url": FULL["apple_url"]})) == ["Listen on Apple Podcasts"]
    assert site.listen_icons({}) == "" and site.listen_icons({"youtube_url": "javascript:alert(1)", "apple_url": ""}) == ""
    assert names(site.listen_icons({"spotify_url": "https://open.spotify.com/show/abc", "spotify_kind": "show"})) == ["Show on Spotify"]
    h = site.listen_icons(FULL)
    assert h.count("<svg") == 3 and "<img" not in h and 'rel="noopener noreferrer"' in h
    out = build_site(tmp_path / "with", FULL)
    for page in ("runs/2026-10-17-weekly/index.html", "index.html", "episodes/rss_a.html"):
        assert names((out / page).read_text()) == ["Watch on YouTube", "Listen on Apple Podcasts", "Listen on Spotify"], page
    md = (out / "runs/2026-10-17-weekly.md").read_text()
    assert "[YouTube](https://www.youtube.com/watch?v=abcdefghijk) · [Apple Podcasts](https://podcasts.apple.com/us/podcast/x/id1?i=2) · [Spotify](https://open.spotify.com/episode/1WAzJv8l0Z9tbMJU0WZM4x)" in md
    ej = json.loads((out / "episodes.json").read_text())["episodes"][0]
    assert (ej["youtube_url"], ej["apple_url"], ej["spotify_url"], ej["spotify_kind"]) == tuple(FULL[k] for k in ("youtube_url", "apple_url", "spotify_url", "spotify_kind"))
    claim = json.loads((out / "claims.jsonl").read_text().splitlines()[0])
    assert claim["link"] == FULL["youtube_url"] + "&t=90s" and claim["apple_url"] == FULL["apple_url"]  # a deep link prefers YouTube
    none = build_site(tmp_path / "none", {})
    assert 'class="listen"' not in (none / "runs/2026-10-17-weekly/index.html").read_text()
    md = (none / "runs/2026-10-17-weekly.md").read_text()
    assert "YouTube" not in md and "Apple Podcasts" not in md and "Spotify" not in md
    assert json.loads((none / "episodes.json").read_text())["episodes"][0]["youtube_url"] is None
    only_show = build_site(tmp_path / "show", {"spotify_url": "https://open.spotify.com/show/abc", "spotify_kind": "show"})
    assert "[Spotify (show)](https://open.spotify.com/show/abc)" in (only_show / "runs/2026-10-17-weekly.md").read_text()


def test_the_report_links_youtube_then_the_listen_page_and_refuses_tracking_and_audio_urls(tmp_path):
    for url in ["https://pdst.fm/e/x", "https://a.com/ep.m4a?x=1", "ftp://x"]:
        assert links.bad_url(url), url
    for url in ["https://www.youtube.com/watch?v=abcdefghijk", "https://allinchamathjason.libsyn.com/some-episode"]:
        assert links.bad_url(url) is None, url
    data = copy.deepcopy(REPORT)
    for e in data["episodes"]:
        e["url"] = "https://traffic.megaphone.fm/a.mp3"
    chosen = [{"episode_id": "yt:a", "youtube_url": "https://www.youtube.com/watch?v=aaaaaaaaaaa"},
              {"episode_id": "yt:b", "listen_url": "https://podcasts.apple.com/us/podcast/x/id1?i=2"}, {"episode_id": "yt:c"}]
    (tmp_path / "selected.json").write_text(json.dumps({"episodes": chosen}))
    report.attach_links(data, tmp_path)
    md = report.render(report.validate(data, "report"))
    assert "1. **[Jane on robots](https://www.youtube.com/watch?v=aaaaaaaaaaa)**" in md
    assert "2. **[Jane on robots](https://podcasts.apple.com/us/podcast/x/id1?i=2)**" in md
    assert "3. **Jane on robots** Widget Show" in md and ".mp3" not in md
    assert "## [Jane on robots](https://www.youtube.com/watch?v=aaaaaaaaaaa)" in md and "aaaaaaaaaaa&t=75s" in md
    bad = copy.deepcopy(REPORT)
    bad["essential"][0]["listen_url"] = "https://chrt.fm/track/x"
    with pytest.raises(RankedError, match="tracking"):
        report.validate(bad, "report")


def chan_xml(chan, titles):
    return f"<feed><title>{chan}</title>" + "".join(f"<entry><title>{t}</title></entry>" for t in titles) + "</feed>"


def test_show_links_are_discovered_filled_verified_and_only_a_wrong_channel_is_blanked(tmp_path, monkeypatch):
    out = ("https://www.youtube.com/channel/UCbloomberg\tBloomberg Podcasts\n"
           "https://www.youtube.com/channel/UCbigtech\tBig Technology Podcast\n")
    assert showlinks.yt_channel_search("Big Technology Podcast", run=lambda cmd: out) == "https://www.youtube.com/channel/UCbigtech"
    assert showlinks.yt_channel_search("Supply Chained", run=lambda cmd: "https://www.youtube.com/channel/UCnow\tSupply Chain Now\n") == ""

    def dead(url, **k):
        raise OSError("HTTP Error 404")

    assert showlinks.channel_titles("UCx", dead, run=lambda cmd: "Semi Doped\tFirst video\nSemi Doped\tSecond video\n") == ("Semi Doped", ["First video", "Second video"])
    assert showlinks.name_like("Apple Events", "Apple") and showlinks.name_like("Sourcery", "Sourcery with Molly O'Shea")
    assert not showlinks.name_like("Supply Chained", "Supply Chain Now") and not showlinks.name_like("Big Technology Podcast", "Bloomberg Podcasts")
    src = {"id": "x", "name": "Show X", "rss": "https://feed/x", "youtube_channel_id": "UCabc"}

    def get(url):
        return {"results": [{"feedUrl": "https://feed/x", "collectionName": "Show X",
                             "collectionViewUrl": "https://podcasts.apple.com/us/podcast/x/id1?uo=4"}]}

    page = 'a <a href="https://www.youtube.com/@spotifyforcreators">y</a> <a href="https://open.spotify.com/show/' + "a" * 22 + '">s</a>'
    pages = {"https://host.buzzsprout.com/1": page, "https://open.spotify.com/show/" + "a" * 22: "<title>Show X | Listen to the Podcast on Spotify</title>"}
    feed = type("F", (), {"feed": {"link": "https://host.buzzsprout.com/1"}})()
    got = showlinks.discover({**src, "youtube_channel_id": None}, get=get, fetch=lambda u: pages[u], parse=lambda u: feed)
    assert got["apple"] == "https://podcasts.apple.com/us/podcast/x/id1" and got["spotify"].endswith("a" * 22)
    assert got["youtube"] == ""  # a hosting platform's page must not donate its own channel
    assert showlinks.discover(src, get=get, fetch=lambda u: pages[u], parse=lambda u: feed)["youtube"].endswith("UCabc")
    assert not showlinks.spotify_ok("u", "Show X", lambda u: "<title>Completely Different Pod | Listen to the Podcast on Spotify</title>")
    good, bad = "g" * 22, "x" * 22
    feed_pages = {"https://feed/x": f"<rss>open.spotify.com/show/{bad} open.spotify.com/show/{good} open.spotify.com/show/{good}</rss>",
                  f"https://open.spotify.com/show/{good}": "<title>Show X | Listen to the Podcast on Spotify</title>",
                  f"https://open.spotify.com/show/{bad}": "<title>Another Show | Listen to the Podcast on Spotify</title>"}
    found = showlinks.discover({"id": "x", "name": "Show X", "rss": "https://feed/x"}, get=lambda u: {"results": []},
                               fetch=lambda u: feed_pages[u], parse=lambda u: type("F", (), {"feed": {}})())
    assert found["spotify"].endswith(good)  # the one whose Spotify page carries the show's name
    # fill never overwrites what a person wrote
    sources = tmp_path / "sources.yaml"
    sources.write_text(yaml.safe_dump({"sources": [src, {"id": "calls-y", "name": "Y call", "rss": "r"}]}))
    path = tmp_path / "show_links.yaml"
    path.write_text(yaml.safe_dump({"x": {"name": "Show X", "site": "https://mine", "youtube": "", "apple": "", "spotify": ""}}))
    changed = showlinks.fill(sources, path, discover_fn=lambda s: {"site": "https://auto", "youtube": "https://yt", "apple": "", "spotify": ""})
    row = showlinks.load(path)["x"]
    assert row["site"] == "https://mine" and row["youtube"] == "https://yt" and row["apple"] == ""
    assert changed == {"x": ["youtube"]} and "calls-y" not in showlinks.load(path) and showlinks.by_name(path)["show x"]["youtube"] == "https://yt"
    assert show_line({"site": "https://s", "youtube": "", "apple": "https://a", "spotify": ""}) == "Show: [Site](https://s) · [Apple](https://a)"
    assert show_line({}) == ""
    # verify: reports, edits nothing; --fix blanks only a channel with another name and other videos
    monkeypatch.setattr(links, "ytdlp_run", lambda *a, **k: (_ for _ in ()).throw(OSError("no yt-dlp in tests")))
    chans = {"a": "Show A", "b": "Show B", "c": "Show C", "d": "Show D"}
    vsrc, vpath = tmp_path / "v-sources.yaml", tmp_path / "v-show_links.yaml"
    vsrc.write_text(yaml.safe_dump({"sources": [{"id": k, "name": v, "rss": f"https://feed/{k}"} for k, v in chans.items()]}))
    vpath.write_text(yaml.safe_dump({k: {"name": v, "site": "", "youtube": f"https://www.youtube.com/channel/UC{k * 22}", "apple": "", "spotify": ""}
                                     for k, v in chans.items()}))
    before = vpath.read_text()
    titles = ["Episode one about chips", "Episode two about power", "Episode three about bonds"]
    xml = {"a": chan_xml("Show A", titles), "b": chan_xml("Other Network", ["Cooking pasta", "Cat videos", "Guitar lesson"]),  # wrong channel
           "c": chan_xml("Show C", ["Cooking pasta", "Cat videos", "Guitar lesson"])}  # right name, retitled videos

    def yt(url):
        k = url.split("UC")[1][0]
        if k == "d":
            raise OSError("timeout")
        return xml[k]

    class Feed:
        entries = [{"title": t} for t in titles]

    rows = showlinks.verify(vsrc, vpath, yt_fetch=yt, parse=lambda u: Feed(), sleep=lambda s: None)
    assert {r["id"]: r["status"] for r in rows} == {"a": "ok", "b": "mismatch", "c": "mismatch", "d": "unreachable"}
    assert vpath.read_text() == before
    assert [r["id"] for r in showlinks.apply_fix(vpath, rows)] == ["b"]  # c is named like the show, d is unreachable
    data = showlinks.load(vpath)
    assert data["b"]["youtube"] == "" and data["a"]["youtube"] and data["c"]["youtube"] and data["d"]["youtube"]
    assert showlinks.classify_youtube(["Cooking pasta", "Cat videos"], ["only one"])[0] == "unreachable"  # thin evidence never blanks a link
    calls = []

    def blocked(url):
        calls.append(url)
        raise showlinks.Blocked("HTTP 429")

    rows = showlinks.verify(vsrc, tmp_path / "v-show_links.yaml", yt_fetch=blocked, parse=lambda u: Feed(), sleep=lambda s: None)
    assert len(calls) == 1 and {r["status"] for r in rows} == {"unreachable"}  # after one block it stops asking YouTube
    assert showlinks.apply_fix(tmp_path / "v-show_links.yaml", rows) == []


def test_transcript_links_prefer_the_publishers_page_then_youtube_captions(tmp_path):
    from sigma.links import backfill_transcript_urls, transcript_link

    assert transcript_link({"transcript_url": "https://cdn.example.com/t/1.html"}) == "https://cdn.example.com/t/1.html"
    assert transcript_link({"transcript_url": "https://x/ep.mp3"}) is None
    assert transcript_link({"transcript_source": "youtube-captions (mirror)", "youtube_id": "abcdefghijk"}) == "https://www.youtube.com/watch?v=abcdefghijk"
    assert transcript_link({"transcript_source": "whisper (30 min)", "youtube_id": "abcdefghijk"}) is None
    (tmp_path / "manifest.json").write_text(json.dumps({"episodes": [
        {"episode_id": "a", "title": "Episode One", "source_tag": "x", "transcript_source": "podcast:transcript"},
        {"episode_id": "b", "title": "Unrelated", "source_tag": "x", "transcript_source": "podcast:transcript"}]}))
    src = tmp_path / "sources.yaml"
    src.write_text(yaml.safe_dump({"sources": [{"id": "x", "name": "X", "rss": "https://feed/x"}]}))
    entry = {"title": "Episode One", "links": [{"rel": "transcript", "href": "https://t/1.vtt", "type": "text/vtt"}]}
    feed = type("F", (), {"entries": [type("E", (dict,), {})(entry)]})()
    assert backfill_transcript_urls(tmp_path, src, parse=lambda u: feed) == {"missing": 2, "found": 1}
    rows = {r["episode_id"]: r for r in json.loads((tmp_path / "manifest.json").read_text())["episodes"]}
    assert rows["a"]["transcript_url"] == "https://t/1.vtt" and "transcript_url" not in rows["b"]
    d = {"week_of": "2026-10-14", "run_dir": "runs/2026-10-21", "ranked_by": "editor", "episodes": [
        {"rank": 1, "episode_id": "yt:1", "title": "Ep 1", "url": "https://www.youtube.com/watch?v=1", "source": "S", "tier": 1,
         "published": "2026-10-19", "score": 9, "reason": "why", "claims": [], "transcript_url": "https://cdn.example.com/t.html"}]}
    assert "](https://cdn.example.com/t.html)" in render(d)
