from __future__ import annotations

import json
import re
import sys
import time
from urllib.parse import urlsplit

import requests

from .config import Source
from . import feedcache


def channel_image(source: Source) -> str | None:
    channel = source.youtube_channel_id
    if not channel:
        path = urlsplit(source.youtube or "").path
        match = re.match(r"/channel/(UC[A-Za-z0-9_-]{22})(?:/|$)", path)
        channel = match[1] if match else None
    if not channel or not re.fullmatch(r"UC[A-Za-z0-9_-]{22}", channel):
        print(f"[show-art] warning: {source.name}: configured YouTube channel ID missing", file=sys.stderr)
        return None
    url = f"https://www.youtube.com/channel/{channel}/about"
    directory = feedcache.cache_dir()
    cached = feedcache._read(url, directory)
    if cached and cached.get("channel_id") == channel and (art := feedcache.image_url(cached.get("image_url"))):
        return art
    try:
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
        response.raise_for_status()
        match = re.search(r'"channelMetadataRenderer"\s*:\s*', response.text)
        if not match:
            raise ValueError("channel metadata missing")
        metadata, _ = json.JSONDecoder().raw_decode(response.text[match.end():])
        if metadata.get("externalId") != channel:
            raise ValueError("channel identity mismatch")
        thumbnails = metadata.get("avatar", {}).get("thumbnails", [])
        art = next((valid for item in sorted(thumbnails, key=lambda item: item.get("width", 0), reverse=True)
                    if (valid := feedcache.image_url(item.get("url")))), None)
        if not art:
            raise ValueError("channel avatar missing")
        feedcache._write(url, directory, {"v": feedcache.VERSION, "url": url, "saved": time.time(),
                                         "channel_id": channel, "image_url": art})
        return art
    except (requests.RequestException, ValueError, TypeError, AttributeError) as error:
        print(f"[show-art] warning: {source.name}: channel artwork unavailable ({type(error).__name__})", file=sys.stderr)
        return None
