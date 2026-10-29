from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

DISCOVERY = {"rss", "itunes", "ytdlp"}
STYLES = ("interview", "influencer")
METHODS = {"podcast_transcript", "whisper", "youtube_captions", "youtube_mirror", "youtube_audio"}
DEFAULTS = {"preferred_source": "rss", "fallback": [], "transcripts": ["podcast_transcript", "whisper"]}


@dataclass
class Source:
    id: str
    name: str
    tier: int  # 1: transcribe every non-news episode, so a show earns it (`wire source review`); 2: triage picks its best episodes, a new show starts here; 3: low priority, at most t3_weekly_cap a week
    style: str = "interview"  # interview (default) or influencer (a creator who picks stocks): influencer episodes are scored apart.
    # Social is the YouTube side, so an influencer needs `youtube:` (load_sources refuses it otherwise); if the creator also has a
    # podcast feed, keep it as a second route with `preferred_source: ytdlp, fallback: [rss]`.
    rss: str | None = None
    youtube: str | None = None
    topics: list[str] = field(default_factory=list)
    preferred_source: str = "rss"
    fallback: list[str] = field(default_factory=list)
    transcripts: list[str] = field(default_factory=list)
    youtube_channel_id: str | None = None  # UC... id; links uses the free channel RSS to find the episode video
    itunes_id: int | None = None  # Apple collection id; person-search hits on this show inherit its tier
    no_search: bool = False  # true: leave this show out of the site's search index (wire search-index); a creator asked, or the owner decided
    news: bool = False  # daily news/market-recap show: not whispered unless transcribe --news
    aliases: list[str] = field(default_factory=list)  # other names Apple or YouTube list the show under

    @property
    def order(self) -> list[str]:
        have = {"rss": bool(self.rss), "itunes": bool(self.itunes_id), "ytdlp": bool(self.youtube)}
        return [s for s in dict.fromkeys([self.preferred_source, *self.fallback]) if have[s]]


def check(owner: str, cfg: dict) -> None:
    bad = ({cfg.get("preferred_source")} | set(cfg.get("fallback", []))) - DISCOVERY
    bad |= set(cfg.get("transcripts", [])) - METHODS
    if bad:
        raise ValueError(f"{owner}: unknown source or method {sorted(bad)}")


def load_sources(path: str | Path) -> tuple[list[Source], int]:
    data = yaml.safe_load(Path(path).read_text())
    defaults = {**DEFAULTS, **data.get("defaults", {})}
    sources = [Source(**{**defaults, **s}) for s in data["sources"]]
    for s in sources:
        if s.tier not in (1, 2, 3):
            raise ValueError(f"{s.id}: tier must be 1, 2 or 3")
        if s.style not in STYLES:
            raise ValueError(f"{s.id}: style must be one of {', '.join(STYLES)}")
        if not (s.rss or s.youtube):
            raise ValueError(f"{s.id}: needs rss or youtube")
        if s.style == "influencer" and not s.youtube:
            raise ValueError(f"{s.id}: an influencer source needs its YouTube channel in `youtube:`. Social is the YouTube side "
                             "and every episode must link to its video, so a creator who does not publish there does not belong in Social")
        check(s.id, vars(s))
    return sources, int(data.get("t3_weekly_cap", 2))
