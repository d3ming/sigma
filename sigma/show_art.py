"""Prepare compact show artwork separately from the offline static renderer."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import struct
import sys
import time
import zlib
from collections.abc import Iterable, Mapping

from .paths import data_root

RECIPE = "png180-fit-no-upscale-v1"
MAX_INPUT = 12 * 1024 * 1024
MAX_OUTPUT = 256 * 1024


def cache_root() -> Path:
    return Path(os.environ.get("SIGMA_SHOW_ART_CACHE") or data_root() / "feed_cache" / "show-art").expanduser()


def cache_file(url: str, cache: Path) -> Path:
    return cache / (hashlib.sha256((RECIPE + "\n" + url).encode()).hexdigest() + ".png")


def png_bytes(path: Path) -> bytes:
    with path.open("rb") as image:
        payload = image.read(MAX_OUTPUT + 1)
    if len(payload) > MAX_OUTPUT or payload[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("invalid compact PNG")
    offset = 8
    first = True
    while offset + 12 <= len(payload):
        length = struct.unpack_from(">I", payload, offset)[0]
        end = offset + 12 + length
        if end > len(payload):
            break
        kind = payload[offset + 4:offset + 8]
        chunk = payload[offset + 4:end - 4]
        if zlib.crc32(chunk) != struct.unpack_from(">I", payload, end - 4)[0]:
            break
        if first:
            if kind != b"IHDR" or length != 13:
                break
            width, height = struct.unpack_from(">II", payload, offset + 8)
            if not (0 < width <= 180 and 0 < height <= 180):
                break
            first = False
        if kind == b"IEND" and length == 0 and end == len(payload):
            return payload
        offset = end
    raise ValueError("invalid compact PNG")


def prepare_show_art(sources: Mapping[str, str], *, cache: Path) -> None:
    import subprocess
    import tempfile
    import urllib.request

    deadline = time.monotonic() + 60
    try:
        cache.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        for show in sources.values():
            print(f"[show-art] warning: {show}: artwork omitted ({type(error).__name__})", file=sys.stderr)
        return
    for url, show in sources.items():
        destination = cache_file(url, cache)
        try:
            png_bytes(destination)
            continue
        except (OSError, ValueError):
            pass
        try:
            if time.monotonic() >= deadline:
                raise TimeoutError("preparation time limit reached")
            with tempfile.TemporaryDirectory(prefix="sigma-show-art-") as temp:
                source, output = Path(temp) / "source", Path(temp) / "art.png"
                request = urllib.request.Request(url, headers={"User-Agent": "Sigma show artwork"})
                with urllib.request.urlopen(request, timeout=min(8, deadline - time.monotonic())) as response, source.open("wb") as target:
                    if response.geturl().split(":", 1)[0] not in {"http", "https"}:
                        raise ValueError("artwork must use HTTP")
                    total = 0
                    while block := response.read1(64 * 1024):
                        total += len(block)
                        if total > MAX_INPUT:
                            raise ValueError("artwork exceeds download limit")
                        if time.monotonic() >= deadline:
                            raise TimeoutError("preparation time limit reached")
                        target.write(block)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("preparation time limit reached")
                subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-protocol_whitelist", "file", "-threads", "1",
                                "-i", str(source), "-vf", "scale=w='min(180,iw)':h='min(180,ih)':force_original_aspect_ratio=decrease",
                                "-frames:v", "1", "-threads", "1", "-c:v", "png", "-compression_level", "9", "-y", str(output)],
                               check=True, timeout=min(5, remaining), capture_output=True)
                payload = png_bytes(output)
                with tempfile.NamedTemporaryFile(dir=cache, suffix=".tmp", delete=False) as staged:
                    staged.write(payload)
                    staged_path = Path(staged.name)
                staged_path.replace(destination)
        except (OSError, ValueError, TimeoutError, subprocess.SubprocessError) as error:
            print(f"[show-art] warning: {show}: artwork omitted ({type(error).__name__})", file=sys.stderr)


def copy_show_art(sources: Mapping[str, str], *, cache: Path, out: Path) -> dict[str, str]:
    mapping = {}
    for url, show in sources.items():
        try:
            payload = png_bytes(cache_file(url, cache))
        except (OSError, ValueError):
            print(f"[show-art] warning: {show}: prepared artwork missing; omitted", file=sys.stderr)
            continue
        name = hashlib.sha256(payload).hexdigest() + ".png"
        target = out / "show-art" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        mapping[url] = "/show-art/" + name
    return mapping


def show_sources(episodes: Iterable[dict]) -> dict[str, str]:
    from urllib.parse import urlsplit

    sources = {}
    for episode in episodes:
        url = episode.get("show_image_url")
        if isinstance(url, str) and urlsplit(url).scheme in {"http", "https"}:
            sources.setdefault(url, episode.get("show") or episode.get("source") or episode.get("title") or "Unnamed show")
    return sources


def main() -> None:
    import argparse
    from .site import load_runs

    parser = argparse.ArgumentParser(description="Prepare cached 180px PNG show art before an offline site build; unavailable artwork is omitted.")
    parser.add_argument("published", type=Path)
    parser.add_argument("--cache", type=Path, default=cache_root())
    args = parser.parse_args()
    episodes = [episode for run in load_runs(args.published) for part in (run, run["influencer"]) for episode in part["meta"].values()]
    sources = show_sources(episodes)
    prepare_show_art(sources, cache=args.cache)
    ready = 0
    for url in sources:
        try:
            png_bytes(cache_file(url, args.cache))
            ready += 1
        except (OSError, ValueError):
            pass
    print(f"[show-art] prepared {ready}/{len(sources)} unique show images")


if __name__ == "__main__":
    main()
