from __future__ import annotations

import sys
import time

import requests

from . import feedcache


def collection_image(collection_id: int, get=None) -> str | None:
    url = f"https://itunes.apple.com/lookup?id={collection_id}"
    directory = feedcache.cache_dir()
    cached = feedcache._read(url, directory)
    if cached and cached.get("collection_id") == collection_id:
        return feedcache.image_url(cached.get("image_url"))
    try:
        response = (get or requests.get)(url, timeout=8)
        response.raise_for_status()
        art = next((image for row in response.json().get("results", [])
                    if row.get("wrapperType") == "track" and row.get("kind") == "podcast"
                    and row.get("collectionId") == collection_id
                    and (image := feedcache.image_url(row.get("artworkUrl600") or row.get("artworkUrl100")))), None)
        if not art:
            raise ValueError("matching collection artwork missing")
        feedcache._write(url, directory, {"v": feedcache.VERSION, "url": url, "saved": time.time(),
                                         "collection_id": collection_id, "image_url": art})
        return art
    except (requests.RequestException, ValueError, TypeError, AttributeError) as error:
        print(f"[show-art] warning: Apple collection {collection_id}: artwork unavailable ({type(error).__name__})", file=sys.stderr)
        return None
