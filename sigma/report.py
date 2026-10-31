from __future__ import annotations

import functools
import json
import re
from decimal import Decimal
from pathlib import Path

import jsonschema

from . import links as _links
from .digest import ts_link
from .ranked import RankedError, forbidden_key, private_hits

SCHEMA = Path(__file__).resolve().parent.parent / "schema"


@functools.lru_cache(maxsize=None)
def _validator(kind: str):
    """One checked validator per schema. `jsonschema.validate` re-checks the schema itself on every call, which was most of the
    time `sigma status` spent (about 17 ms a call, 137 calls in the daily-loop test)."""
    schema = json.loads((SCHEMA / f"{kind}.schema.json").read_text())
    cls = jsonschema.validators.validator_for(schema)
    cls.check_schema(schema)
    return cls(schema)


def validate(data: dict, kind: str) -> dict:
    try:
        if (err := jsonschema.exceptions.best_match(_validator(kind).iter_errors(data))) is not None:
            raise err
    except jsonschema.ValidationError as exc:
        raise RankedError(f"{kind}: {'/'.join(map(str, exc.absolute_path)) or 'root'}: {exc.message}") from None
    if forbidden_key(data):
        raise RankedError(f"{kind}: holdings-like fields are not allowed")
    if hits := private_hits(data):
        raise RankedError(f"{kind}: private text is not allowed: {hits}")
    if kind == "selected":
        bad = [e["episode_id"] for e in data["episodes"] if e.get("fallback_text") and "fallback" not in e["why"].lower()]
        if bad:
            raise RankedError(f"selected: fallback_text picks must say 'fallback' in why: {bad}")
    if kind == "report":
        ids = [e["episode_id"] for e in data["essential"]]
        if [e["episode_id"] for e in data["episodes"]] != ids:
            raise RankedError(f"report: episodes must match essential one to one, in the same order: {ids}")
        from .links import bad_url
        for e in data["essential"] + data["episodes"]:
            if e.get("listen_url") and (why := bad_url(e["listen_url"])):
                raise RankedError(f"report: {e['episode_id']} listen_url is {why}: {e['listen_url']}")
    return data


PARAPHRASE_WORDS = 12  # a run this long copied verbatim from the transcript is a quote, not a paraphrase
TS_SLACK = 30  # seconds a timestamp may run past the last transcript line


def _words(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).split()


def _norm_name(name: str) -> str:
    return " ".join(_words(name))


def _load_transcript(run_dir: Path, row: dict) -> tuple[float | None, set[tuple[str, ...]], list[tuple[float, str | None]]]:
    """(last timestamp, copied-word runs, explicit speaker labels) for the episode's .md."""
    from .fetch import segments_from_md

    md = run_dir / row["file"] if row.get("file") else None
    segs = segments_from_md(md.read_text()) if md and md.exists() else []
    if not segs:
        return None, set(), []
    words = _words(" ".join(re.sub(r"^(?:speaker\s*\d+:)\s*", "", s["text"], flags=re.I) for s in segs))
    n = PARAPHRASE_WORDS
    grams = {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}
    return max(s["start"] for s in segs), grams, [(s["start"], _explicit_speaker(s["text"])) for s in segs]


def _explicit_speaker(text: str) -> str | None:
    m = re.match(
        r"^([A-Z][A-Za-z0-9.'’\-]*(?:\s+(?:[A-Z][A-Za-z0-9.'’\-]*|speaker|host|guest|interviewer|moderator|analyst|ceo|cfo|of|de|van)){1,5}"
        r"(?:\s+\([A-Za-z0-9 ._'-]{1,40}\))?):\s+\S", text)
    if m:
        return m.group(1).strip()
    role = re.match(r"^(Host|Guest|Interviewer|Moderator|Analyst|CEO|CFO|Speaker\s+\d+):\s+\S", text, re.I)
    return role.group(1).strip() if role else None


def _speaker_keys(name: str) -> set[str]:
    keys = {_norm_name(name)}
    base = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
    if base != name:
        keys.add(_norm_name(base))
    return keys


def _speaker_error(name: str | None, timestamp: int | None, labels: list[tuple[float, str | None]]) -> str | None:
    if not name or _norm_name(name) in {"unknown", "unidentified"} or timestamp is None:
        return None
    starts = [ts for ts, _ in labels if ts <= timestamp]
    if not starts:
        return None
    nearest = max(starts)
    current = [label for ts, label in labels if ts == nearest]
    if any(label is None for label in current):
        return None
    at_time = current
    if not at_time or any(_speaker_keys(name) & _speaker_keys(label) for label in at_time):
        return None
    return ", ".join(dict.fromkeys(at_time))


def _longest_copy(text: str, grams: set[tuple[str, ...]]) -> list[str]:
    """The longest run of words from text that is also in the transcript (>= PARAPHRASE_WORDS), else []."""
    words, n = _words(text), PARAPHRASE_WORDS
    best: list[str] = []
    i = 0
    while i + n <= len(words):
        if tuple(words[i:i + n]) in grams:
            j = i + n
            while j < len(words) and tuple(words[j - n + 1:j + 1]) in grams:
                j += 1
            if j - i > len(best):
                best = words[i:j]
            i = j - n + 1
        i += 1
    return best


MIN_PICKS = 3  # a day surfaces at least this many episodes when the scores allow it, and every 6+ with no upper limit
HARD_REJECTS = {"news_show", "recap", "clip", "hosts_only", "speaker_other", "duplicate_person", "rerun"}  # rules that leave a candidate unpickable


def _verify_floor(data: dict, by_id: dict, scores: dict) -> list[str]:
    """The selection floor, against scores.json (id -> score of a podcast episode): every 6+ is picked or has a stated reason;
    fewer than MIN_PICKS picks are filled from the best 5s, flagged lower_confidence; nothing below 5 is picked."""
    from .fetch import is_news

    errs, picks = [], {e["episode_id"]: e for e in data["episodes"]}
    left = {x["episode_id"]: x["reason"] for x in data.get("left_out", [])}
    for eid in left:
        if eid in picks:
            errs.append(f"selected: left_out lists {eid}, which is also picked")
    from .rank import is_influencer

    n = sum(1 for i in picks if not is_influencer(by_id.get(i) or {}))  # the floor counts podcast interviews only, never Social/influencer videos
    low = [i for i, e in picks.items() if e.get("lower_confidence")]
    for eid, e in picks.items():
        s = scores.get(eid)
        if s is None and e.get("fallback_text"):
            continue  # a description-only pick is never read or scored (select.md allows it, labeled)
        if s is None:
            errs.append(f"selected: {eid} is not in scores.json (only scored episodes can be picked)")
        elif s < 5:
            errs.append(f"selected: {eid} scored {s}; nothing below 5 is picked, even to reach {MIN_PICKS}")
        elif s >= 6 and e.get("lower_confidence"):
            errs.append(f"selected: {eid} scored {s}: lower_confidence is only for a 5 (a 6+ is a full pick)")
        elif s == 5 and not e.get("lower_confidence"):
            errs.append(f"selected: {eid} scored 5: set lower_confidence: true (a 5 is picked only to fill up to {MIN_PICKS})")
    if low and n > MIN_PICKS:
        errs.append(f"selected: {len(low)} lower_confidence pick(s) with {n} picks; a 5 is added only to reach {MIN_PICKS}, so drop it")
    live = {i: s for i, s in scores.items() if i in by_id and not by_id[i].get("rerun") and not is_news(by_id[i])}
    for eid in sorted((i for i, s in live.items() if s >= 6 and i not in picks and i not in left)):
        errs.append(f"selected: {eid} scored {live[eid]} but is neither picked nor in left_out (every 6+ is picked unless a rule rejects it)")
    pool = [i for i, s in sorted(live.items(), key=lambda kv: -kv[1]) if s >= 5 and i not in picks and left.get(i) not in HARD_REJECTS]
    if n < MIN_PICKS and pool:
        errs.append(f"selected: {n} pick(s), minimum {MIN_PICKS}: add the best of {pool[:5]} as lower_confidence (score 5) "
                    "or list each in left_out with a rule that rejects it (news_show, recap, clip, hosts_only, speaker_other, duplicate_person, rerun)")
    return errs


def _verify_selected(data: dict, by_id: dict, scores: dict | None = None) -> list[str]:
    errs, seen, owner = [], set(), {}
    for i, e in enumerate(data["episodes"]):
        eid, where = e["episode_id"], f"selected: episodes[{i}] {e['episode_id']}"
        if eid in seen:
            errs.append(f"{where}: duplicate episode_id (picks must be distinct)")
        seen.add(eid)
        row = by_id.get(eid)
        if row is None:
            errs.append(f"{where}: not in manifest.json")
            continue
        if row.get("rerun"):
            errs.append(f"{where}: manifest marks it rerun: true (replay/re-air)")
        from .rank import is_influencer

        if is_influencer(row):
            errs.append(f"{where}: an influencer (Social) episode is not a podcast pick; the daily issue and its floor of {MIN_PICKS} count podcast interviews only")
        if "has_transcript" in e and bool(e["has_transcript"]) != bool(row.get("has_transcript")):
            errs.append(f"{where}: has_transcript is {e['has_transcript']} but manifest says {bool(row.get('has_transcript'))}")
        if bool(e.get("fallback_text")) != bool(row.get("fallback_text")):
            errs.append(f"{where}: fallback_text is {bool(e.get('fallback_text'))} but manifest says {bool(row.get('fallback_text'))}")
        for g in e["guests"]:
            if "host" in (g.get("role") or "").lower() or not _norm_name(g["name"]):
                continue
            key = _norm_name(g["name"])
            if key in owner and owner[key] != eid:
                errs.append(f"{where}: guest {g['name']!r} also picked in {owner[key]} (one pick per person)")
            owner.setdefault(key, eid)
    if scores:
        errs += _verify_floor(data, by_id, scores)
    return errs


def _podcast_scores(run_dir: Path) -> dict:
    """{episode_id: score} from the run's scores.json; {} when it is absent or unreadable (the floor then cannot be checked)."""
    try:
        rows = json.loads((run_dir / "scores.json").read_text()).get("episodes") or []
        return {r["episode_id"]: r["score"] for r in rows if isinstance(r, dict) and isinstance(r.get("score"), int)}
    except (OSError, ValueError, KeyError, AttributeError):
        return {}


def _cites(ep: dict):
    for i, c in enumerate(ep["signal"]):
        yield f"signal[{i}]", c
    for si, s in enumerate(ep["sections"]):
        for ci, c in enumerate(s.get("claims", [])):
            yield f"sections[{si}].claims[{ci}]", c


def _verify_report(data: dict, by_id: dict, run_dir: Path) -> list[str]:
    errs = []
    sel_p = run_dir / "selected.json"
    if sel_p.exists():
        try:
            want = {e["episode_id"] for e in json.loads(sel_p.read_text())["episodes"]}
        except (ValueError, KeyError, TypeError) as exc:
            errs.append(f"report: selected.json is unreadable ({exc})")
        else:
            low = {e["episode_id"] for e in json.loads(sel_p.read_text())["episodes"] if e.get("lower_confidence")}
            if {e["episode_id"] for e in data["essential"] if e.get("lower_confidence")} != low:
                errs.append(f"report: essential lower_confidence differs from selected.json (should be {sorted(low)})")
            for part in ("essential", "episodes"):
                got = {e["episode_id"] for e in data[part]}
                if got != want:
                    errs.append(f"report: {part} episode_ids differ from selected.json: "
                                f"missing {sorted(want - got)}, not selected {sorted(got - want)}")
    for ep in data["episodes"]:
        eid = ep["episode_id"]
        row = by_id.get(eid)
        if row is None:
            errs.append(f"report: {eid}: not in manifest.json")
            continue
        real = bool(row.get("has_transcript"))
        last, grams, speaker_labels = _load_transcript(run_dir, row)
        if real and last is None:
            errs.append(f"report: {eid}: manifest has_transcript but {row.get('file')} has no [h:mm:ss] transcript lines")
        if not real and any(True for _ in _cites(ep)):
            errs.append(f"report: {eid}: claims cannot be grounded because the manifest says there is no real transcript")
        for where, c in _cites(ep):
            ts = c["timestamp"]
            if labels := _speaker_error(c.get("speaker"), ts, speaker_labels):
                errs.append(f"report: {eid} {where}: speaker {c.get('speaker')!r} does not match transcript label "
                            f"{labels!r} at {_clock(ts)}")
            if ts is None and real:
                errs.append(f"report: {eid} {where}: timestamp is null but the episode has a transcript")
            elif ts is not None and not real:
                errs.append(f"report: {eid} {where}: timestamp {ts} but the manifest says no real transcript (use null)")
            elif ts is not None and last is not None and ts > last + TS_SLACK:
                errs.append(f"report: {eid} {where}: timestamp {ts}s is past the end of the transcript "
                            f"({int(last)}s, +{TS_SLACK}s allowed)")
        fields = [(f"{w}.text", c["text"]) for w, c in _cites(ep)]
        fields += [(f"sections[{i}].body", s["body"]) for i, s in enumerate(ep["sections"])]
        for where, text in fields:
            if run := _longest_copy(text, grams):
                errs.append(f"report: {eid} {where}: {len(run)} consecutive words copied verbatim from the transcript "
                            f"(paraphrase; {PARAPHRASE_WORDS}+ is rejected): \"{' '.join(run[:PARAPHRASE_WORDS])}...\"")
    return errs


def verify(kind: str, data: dict, run_dir: Path) -> list[str]:
    """Check a schema-valid selected/report against the run folder. Deterministic, no network.
    Returns every problem found. A report with claims needs a readable manifest; unclaimed data can still be checked
    without one."""
    man_p = Path(run_dir) / "manifest.json"
    run_dir = Path(run_dir)
    try:
        by_id = {e["episode_id"]: e for e in json.loads(man_p.read_text()).get("episodes", [])}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        if kind == "report" and any(any(True for _ in _cites(e)) for e in data.get("episodes", [])):
            return [f"report: cannot ground claims; manifest.json is missing or unreadable ({exc})"]
        return []
    if kind == "selected":
        return _verify_selected(data, by_id, _podcast_scores(run_dir))
    if kind == "report":
        return _verify_report(data, by_id, run_dir)
    return []


NUM_WINDOW = 120  # seconds either side of a cite's timestamp in which each of its numbers should be spoken
_UNITS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
    "seventeen eighteen nineteen".split())}
_TENS = {w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if w != "_"}
_MAGNITUDE_SCALE = {"thousand": Decimal(1_000), "million": Decimal(1_000_000),
                    "billion": Decimal(1_000_000_000), "trillion": Decimal(1_000_000_000_000),
                    "k": Decimal(1_000), "m": Decimal(1_000_000), "b": Decimal(1_000_000_000),
                    "bn": Decimal(1_000_000_000), "t": Decimal(1_000_000_000_000)}
_MAGNITUDE_SCALE.update({f"{unit}s": scale for unit, scale in tuple(_MAGNITUDE_SCALE.items()) if len(unit) > 1})
_MAGNITUDES = set(_MAGNITUDE_SCALE)
_PERCENT_WORDS = {"percent", "percentage", "%"}
_NUM_TOKEN = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?|[a-z]+|%")
_CITE_NUMBER = re.compile(
    r"(?<![A-Za-z\d.,])(?P<number>\d+(?:,\d{3})*(?:\.\d+)?)"
    r"(?P<suffix>\s*(?:%|bn\b|[bmktx]\b))?"
    r"(?P<unit>\s+(?:thousands?|millions?|billions?|trillions?|percent(?:age)?))?(?![A-Za-z])", re.I)


def _num_key(v: float | Decimal, unit: str | None = None) -> str:
    value = Decimal(str(v))
    if unit in _PERCENT_WORDS or unit == "%":
        return f"percent:{format(value.normalize(), 'f')}"
    if unit:
        value *= _MAGNITUDE_SCALE[unit.lower()]
    return format(value.normalize(), "f")


def _shared_range_unit(value: Decimal, other: str, unit: str) -> str | None:
    other_value = Decimal(other.replace(",", ""))
    scale = _MAGNITUDE_SCALE.get(unit)
    if scale and value >= 1000 > other_value and value < other_value * scale:
        return None
    return unit


def cite_numbers(text: str) -> list[tuple[str, str]]:
    """Numbers worth checking in a cite as (unit-aware key, display text).
    Whole numbers 0-9 and years 2000-2099 are skipped as too noisy (decimals like 1.5 are kept)."""
    out = []
    matches = list(_CITE_NUMBER.finditer(text))
    for i, match in enumerate(matches):
        token = match.group("number")
        unit = (match.group("unit") or match.group("suffix") or "").strip().lower()
        if not unit:
            for j in (i - 1, i + 1):
                if not 0 <= j < len(matches):
                    continue
                other = matches[j]
                gap = text[match.end():other.start()] if j > i else text[other.end():match.start()]
                other_unit = (other.group("unit") or other.group("suffix") or "").strip().lower()
                left = match if j > i else other
                between = re.search(r"\bbetween\s+\$?\s*$", text[:left.start()], re.I)
                if other_unit and (re.fullmatch(r"\s*(?:[-–—]|to|through|or)\s*\$?\s*", gap, re.I) or
                                   (j > i and between and re.fullmatch(r"\s+and\s+\$?\s*", gap, re.I))):
                    unit = _shared_range_unit(Decimal(token.replace(",", "")), other.group("number"), other_unit) or ""
                    break
        if unit.endswith("s") and unit[:-1] in _MAGNITUDE_SCALE:
            unit = unit[:-1]
        if unit == "x":
            unit = ""
        value = Decimal(token.replace(",", ""))
        whole = "." not in token
        if not unit and whole and (value < 10 or 2000 <= value <= 2099):
            continue
        item = (_num_key(value, unit), token)
        if item[0] not in {key for key, _ in out}:
            out.append(item)
    return out


def spoken_numbers(words: list[tuple[str, float]]) -> list[tuple[float, str]]:
    """Every number in a (word, timestamp) stream as (timestamp, key): digits, and spelled out ones
    (one..nineteen, twenty..ninety, hundred, 'twenty five', 'two hundred', 'one point four') as digits."""
    out, i, n = [], 0, len(words)
    while i < n:
        w, ts = words[i]
        if w == "a" and i + 4 < n and words[i + 1][0] in _MAGNITUDES and \
                [words[i + k][0] for k in range(2, 5)] == ["and", "a", "half"]:
            unit = words[i + 1][0]
            next_unit = words[i + 5][0] if i + 5 < n and words[i + 5][0] in _MAGNITUDES else None
            if next_unit and next_unit != unit:
                i += 6
                continue
            out.append((ts, _num_key(1.5, unit)))
            i += 6 if next_unit else 5
            continue
        if w[0].isdigit():
            value = Decimal(w.replace(",", ""))
            unit = words[i + 1][0] if i + 1 < n and words[i + 1][0] in _MAGNITUDES | _PERCENT_WORDS else None
            if unit is None and i + 3 < n and words[i + 1][0] in {"to", "through", "or"} and \
                    words[i + 2][0][:1].isdigit() and words[i + 3][0] in _MAGNITUDES | _PERCENT_WORDS:
                unit = _shared_range_unit(value, words[i + 2][0], words[i + 3][0])
            if unit is None and i > 0 and words[i - 1][0] == "between" and i + 3 < n and \
                    words[i + 1][0] == "and" and words[i + 2][0][:1].isdigit() and \
                    words[i + 3][0] in _MAGNITUDES | _PERCENT_WORDS:
                unit = _shared_range_unit(value, words[i + 2][0], words[i + 3][0])
            if unit is None and i + 2 < n and words[i + 1][0][:1].isdigit() and \
                    words[i + 2][0] in _MAGNITUDES | _PERCENT_WORDS:
                unit = _shared_range_unit(value, words[i + 1][0], words[i + 2][0])
            out.append((ts, _num_key(value, unit)))
            i += 2 if i + 1 < n and words[i + 1][0] in _MAGNITUDES | _PERCENT_WORDS else 1
            continue
        if w in _UNITS or w in _TENS or w == "hundred" or (w == "a" and i + 1 < n and words[i + 1][0] in _MAGNITUDES):
            cur, j = 0, i
            magnitude = None
            while j < n:
                x = words[j][0]
                r = cur % 100
                if x == "a" and cur == 0 and j + 1 < n and words[j + 1][0] in _MAGNITUDES:
                    cur = 1
                elif x in _UNITS and (r == 0 or (r >= 20 and r % 10 == 0 and _UNITS[x] < 10)):
                    cur += _UNITS[x]
                elif x in _TENS and r == 0:
                    cur += _TENS[x]
                elif x == "hundred" and cur < 100:
                    cur = (cur or 1) * 100
                elif x in _MAGNITUDES and x.rstrip("s") == "thousand":
                    cur = (cur or 1) * 1000
                elif x == "and" and cur >= 100 and j + 1 < n and (words[j + 1][0] in _UNITS or words[j + 1][0] in _TENS):
                    pass
                elif x == "and" and cur > 0 and j + 2 < n and [words[j + 1][0], words[j + 2][0]] == ["a", "half"]:
                    cur += 0.5
                    j += 2
                else:
                    break
                j += 1
            if j + 3 < n and words[j][0] in _MAGNITUDES and \
                    [words[j + k][0] for k in range(1, 4)] == ["and", "a", "half"] and cur > 0:
                next_unit = words[j + 4][0] if j + 4 < n and words[j + 4][0] in _MAGNITUDES else None
                if next_unit and next_unit != words[j][0]:
                    i = j + 5
                    continue
                cur += 0.5
                magnitude = words[j][0]
                j += 5 if next_unit else 4
            val = str(cur) if cur % 1 else str(int(cur))
            if j + 1 < n and words[j][0] == "point" and words[j + 1][0] in _UNITS and _UNITS[words[j + 1][0]] < 10:
                k = j + 1
                while k < n and words[k][0] in _UNITS and _UNITS[words[k][0]] < 10:
                    val += ("." if "." not in val else "") + str(_UNITS[words[k][0]])
                    k += 1
                j = k
            if magnitude is None and j < n and words[j][0] in _MAGNITUDES:
                magnitude = words[j][0]
                j += 1
            unit = magnitude
            if unit is None and j < n and words[j][0] in _PERCENT_WORDS:
                unit = words[j][0]
                j += 1
            out.append((ts, _num_key(Decimal(val), unit)))
            i = j
            continue
        i += 1
    return out


def _clock(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def _stream(segs: list[dict]) -> list[tuple[str, float]]:
    """(word, segment start) for every word of the segments; speaker prefixes and hyphens removed."""
    return [(w, s["start"]) for s in segs
            for w in _NUM_TOKEN.findall(re.sub(r"^(?:speaker\s*\d+:)\s*", "", s["text"], flags=re.I).lower().replace("-", " "))]


def _number_index(run_dir: Path, row: dict) -> list[tuple[float, str]]:
    from .fetch import segments_from_md

    md = run_dir / row["file"] if row.get("file") else None
    return spoken_numbers(_stream(segments_from_md(md.read_text()) if md and md.exists() else []))


def _short(headline: str | None, n: int = 40) -> str:
    h = " ".join((headline or "").replace('"', "'").split())
    return f' "{h[:n].rstrip()}{"..." if len(h) > n else ""}"' if h else ""


def _number_warnings(ep: dict, index: list[tuple[float, str]], source: str = "transcript") -> list[str]:
    """One line per cite number not spoken near its timestamp. `source` is the label shown in [..]: transcript|captions.
    Shape (parsed by dedupe_warnings): "report: <eid> "<headline>" <cite position>: number N not spoken within Ws of
    H:MM:SS (ts Ns) [source]; <nearest mention and what to do>"."""
    out = []
    for where, c in _cites(ep):
        ts = c["timestamp"]
        if ts is None:
            continue
        near = {k for t, k in index if abs(t - ts) <= NUM_WINDOW}
        for key, num in cite_numbers(c["text"]):
            if key in near:
                continue
            spoken = [t for t, k in index if k == key]
            if spoken:
                t = min(spoken, key=lambda x: abs(x - ts))
                tail = (f"nearest mention {_clock(t)} ({int(abs(t - ts))}s {'later' if t > ts else 'earlier'}); "
                        f"move the timestamp there or fix the number")
            else:
                tail = f"not spoken anywhere in the {source}; fix or drop the number"
            out.append(f"report: {ep['episode_id']}{_short(ep.get('headline'))} {where}: number {num} not spoken within "
                       f"{NUM_WINDOW}s of {_clock(ts)} (ts {int(ts)}s) [{source}]; {tail}")
    return out


_NUM_WARN = re.compile(r'^(?P<pre>(?:report|ranked): \S+(?: "[^"]*")? \S+: number \S+ not spoken within \d+s of \S+ \(ts \d+s\)) '
                       r'\[(?P<src>[^\]]+)\]; (?P<tail>.*)$')


def dedupe_warnings(warnings: list[str]) -> list[str]:
    """Collapse repeats, keeping first-seen order. Number warnings (same episode, cite position, number and timestamp)
    from different checks merge into one line that names every source, e.g. "[transcript, captions]" with each
    source's nearest mention. Any other line is only de-duplicated when identical."""
    merged: dict[str, dict] = {}
    for w in warnings:
        m = _NUM_WARN.match(w)
        key = m.group("pre") if m else w
        slot = merged.setdefault(key, {"line": w, "tails": {}} if m else {"line": w})
        if m:
            slot["tails"].setdefault(m.group("src"), m.group("tail"))
    out = []
    for key, slot in merged.items():
        tails = slot.get("tails")
        if not tails or len(tails) == 1:
            out.append(slot["line"])
        else:
            out.append(f"{key} [{', '.join(tails)}]; " + "; ".join(f"{src}: {t}" for src, t in tails.items()))
    return out


def warn(kind: str, data: dict, run_dir: Path) -> list[str]:
    """Soft checks that never fail a run: each number (>= 10, not a 2000s year) in a report cite should be spoken
    within NUM_WINDOW seconds of the cite's timestamp. Catches in-range but wrong timestamps and misheard figures."""
    man_p = Path(run_dir) / "manifest.json"
    if kind != "report" or not man_p.exists():
        return []
    run_dir = Path(run_dir)
    by_id = {e["episode_id"]: e for e in json.loads(man_p.read_text()).get("episodes", [])}
    out = []
    for ep in data["episodes"]:
        row = by_id.get(ep["episode_id"])
        if row is not None and row.get("has_transcript"):
            if _load_transcript(run_dir, row)[0] is None:
                out.append(f"report: {ep['episode_id']}{_short(ep.get('headline'))}: transcript {row.get('file')} is "
                           f"missing or has no [h:mm:ss] lines; number check skipped")
                continue
            out += _number_warnings(ep, _number_index(run_dir, row))
    return dedupe_warnings(out)


def _ranked_cites(e: dict) -> dict:
    return {"episode_id": e["episode_id"], "headline": e.get("title"), "sections": [],
            "signal": [{"text": c["claim"], "timestamp": c["timestamp"]} for c in e["claims"]]}


def ranked_verify(data: dict, run_dir: Path) -> tuple[list[str], list[str]]:
    """(errors, warnings) for a weekly ranked.json against its run folder.
    Claims without a readable manifest or usable transcript are errors. A manifest episode with no claims can still be
    listed without a transcript.
    Errors: id not in the manifest, claims on an episode without a real transcript, timestamp past the transcript end,
    a 12-word verbatim run. Warnings: numbers in a claim not spoken within NUM_WINDOW seconds of its timestamp."""
    errs, warns = ranked_check(data, run_dir)
    return [msg for _, _, msg in errs], warns


def ranked_check(data: dict, run_dir: Path) -> tuple[list[tuple[str, int | None, str]], list[str]]:
    """The checks behind ranked_verify, with each error tied to its place: ([(episode_id, claim index, or None for the
    whole episode, message)], warnings). A claim without a readable manifest and transcript is an error. themes.py uses
    the places to tell whether a claim it cites passed."""
    run_dir = Path(run_dir)
    man_p = run_dir / "manifest.json"
    try:
        by_id = {e["episode_id"]: e for e in json.loads(man_p.read_text()).get("episodes", [])}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        errors = [(e.get("episode_id", "?"), None,
                   f"ranked: {e.get('episode_id', '?')}: cannot ground claims; manifest.json is missing or unreadable ({exc})")
                  for e in data.get("episodes", []) if e.get("claims")]
        return errors, [] if errors else [f"ranked: manifest.json in {run_dir} is missing or unreadable ({exc})"]
    errs, warns = [], []
    for e in data["episodes"]:
        eid, row = e["episode_id"], by_id.get(e["episode_id"])
        if row is None:
            errs.append((eid, None, f"ranked: {eid}: not in manifest.json"))
            continue
        if not row.get("has_transcript"):
            if e["claims"]:
                errs.append((eid, None, f"ranked: {eid}: has claims but the manifest says no real transcript"))
            continue
        last, grams, speaker_labels = _load_transcript(run_dir, row)
        if last is None:
            if e["claims"]:
                errs.append((eid, None, f"ranked: {eid}: transcript {row.get('file')} is missing or has no [h:mm:ss] lines; "
                             f"{len(e['claims'])} claims cannot be grounded"))
            continue
        for i, c in enumerate(e["claims"]):
            if c["timestamp"] > last + TS_SLACK:
                errs.append((eid, i, f"ranked: {eid} claims[{i}]: timestamp {c['timestamp']}s is past the end of the transcript ({int(last)}s)"))
            if labels := _speaker_error(c.get("speaker"), c["timestamp"], speaker_labels):
                errs.append((eid, i, f"ranked: {eid} claims[{i}]: speaker {c.get('speaker')!r} does not match transcript label "
                                     f"{labels!r} at {_clock(c['timestamp'])}"))
            if run := _longest_copy(c["claim"], grams):
                errs.append((eid, i, f"ranked: {eid} claims[{i}]: {len(run)} consecutive words copied verbatim from the transcript"))
        warns += _number_warnings(_ranked_cites(e), _number_index(run_dir, row))
    return errs, dedupe_warnings([w.replace("report: ", "ranked: ", 1).replace(" signal[", " claims[") for w in warns])


OFFSET_MIN_SECONDS = 45  # median cite-vs-video drift that is reported
OFFSET_MIN_NUMBERS = 3
OFFSET_MAX_PAIR = 600  # a caption mention further than this from the cite is a different mention, not drift


def estimate_offset(ep: dict, index: list[tuple[float, str]]) -> tuple[float, int] | None:
    """Median of (cited - spoken) seconds over cite numbers, using each number's nearest mention. (median, samples)."""
    deltas = []
    for _, c in _cites(ep):
        if c["timestamp"] is None:
            continue
        for key, _ in cite_numbers(c["text"]):
            spoken = [t for t, k in index if k == key]
            if not spoken:
                continue
            delta = c["timestamp"] - min(spoken, key=lambda t: abs(t - c["timestamp"]))
            if abs(delta) <= OFFSET_MAX_PAIR:
                deltas.append(delta)
    if not deltas:
        return None
    deltas.sort()
    mid = len(deltas) // 2
    return (deltas[mid] if len(deltas) % 2 else (deltas[mid - 1] + deltas[mid]) / 2), len(deltas)


def caption_warn(data: dict, run_dir: Path, fetch=None) -> list[str]:
    """Opt-in, network: compare cites with the linked YouTube video's captions (youtube_url in the report or
    selected.json). Same number-near-timestamp warnings plus a per-episode drift estimate. Never raises: a fetch
    failure, empty captions or malformed caption segments give one "skipped:" line for that episode."""
    from .links import yt_id

    if fetch is None:
        try:
            from .transcribe import from_youtube as fetch
        except Exception as exc:  # optional dependency missing
            return [f"report: captions check skipped: cannot load the YouTube caption fetcher ({type(exc).__name__}: {exc})"]
    sel = {}
    try:
        if (Path(run_dir) / "selected.json").exists():
            sel = {e["episode_id"]: e for e in json.loads((Path(run_dir) / "selected.json").read_text())["episodes"]}
    except (ValueError, KeyError, TypeError):
        pass
    out = []
    for ep in data["episodes"]:
        eid = ep["episode_id"]
        url = ep.get("youtube_url") or next((e.get("youtube_url") for e in data["essential"] if e["episode_id"] == eid), None) \
            or sel.get(eid, {}).get("youtube_url")
        vid = yt_id(url)
        if not vid:
            continue
        who = f"report: {eid}{_short(ep.get('headline'))}"
        try:
            segs = fetch(vid)
        except Exception as exc:
            out.append(f"{who}: skipped: could not fetch YouTube captions for {vid} ({type(exc).__name__}); "
                       f"cites not checked against captions")
            continue
        if not segs:
            out.append(f"{who}: skipped: no YouTube captions for {vid}; cites not checked against captions")
            continue
        try:
            index = spoken_numbers(_stream(segs))
            lines = _number_warnings(ep, index, "captions")
            est = estimate_offset(ep, index)
        except Exception as exc:  # malformed caption segments
            out.append(f"{who}: skipped: unusable YouTube captions for {vid} ({type(exc).__name__}); "
                       f"cites not checked against captions")
            continue
        out += lines
        if est and est[1] >= OFFSET_MIN_NUMBERS and abs(est[0]) >= OFFSET_MIN_SECONDS:
            out.append(f"{who}: cite timestamps run {round(abs(est[0]))}s {'later' if est[0] > 0 else 'earlier'} "
                       f"than the linked YouTube video (median over {est[1]} numbers); shift them to match the video")
    return dedupe_warnings(out)


def cite(c: dict, url: str) -> str:
    where = ", ".join(x for x in (c["speaker"], ts_link(url, c["timestamp"]) if c["timestamp"] is not None else "") if x)
    read = f" (our read: {c['our_read']})" if c.get("our_read") else ""
    return f"- {c['text']} [{where}]{read}"


def attach_links(data: dict, run_dir: Path | None) -> dict:
    """Fill youtube_url / listen_url on essential and episodes from selected.json; never audio or tracking."""
    from .links import bad_url
    sel = {}
    if run_dir and (run_dir / "selected.json").exists():
        sel = {e["episode_id"]: e for e in json.loads((run_dir / "selected.json").read_text())["episodes"]}
    eps = {e["episode_id"]: e for e in data["episodes"]}
    man = {}
    if run_dir and (run_dir / "manifest.json").exists():
        man = {r["episode_id"]: r for r in json.loads((run_dir / "manifest.json").read_text()).get("episodes", [])}
    for e in data["episodes"]:
        if not e.get("transcript_url") and (u := _links.transcript_link(man.get(e["episode_id"], {}))):
            e["transcript_url"] = u
    for e in data["essential"] + data["episodes"]:
        s, ep = sel.get(e["episode_id"], {}), eps.get(e["episode_id"], {})
        for k in ("youtube_url", "listen_url"):
            if not e.get(k) and (v := s.get(k) or ep.get(k)):
                e[k] = v
        if not e.get("listen_url") and ep.get("url") and not bad_url(ep["url"]):
            e["listen_url"] = ep["url"]
    return data


def best_link(e: dict) -> str | None:
    """YouTube first, then Apple/Spotify/episode page (listen_url), then a non-audio url."""
    from .links import bad_url
    for u in (e.get("youtube_url"), e.get("listen_url"), e.get("url")):
        if u and not bad_url(u):
            return u
    return None


def essential_line(i: int, e: dict) -> str:
    head = f"[{e['headline']}]({u})" if (u := best_link(e)) else e["headline"]
    return f"{i}. **{head}** {e['show']}, with {e['guests']}" + (" (lower confidence)" if e.get("lower_confidence") else "")


def render(data: dict) -> str:
    lines = [f"# {data['title']}", "", "## Key Insights", ""] + [f"- {k}" for k in data["key_insights"]]
    lines += ["", "## Essential Episodes", ""]
    lines += [essential_line(i, e) for i, e in enumerate(data["essential"], 1)]
    for ep in data["episodes"]:
        head = f"[{ep['headline']}]({u})" if (u := best_link(ep)) else ep["headline"]
        lines += ["", "---", "", f"## {head}"]
        if (tu := ep.get("transcript_url")):
            lines += ["", f"Transcript: [{_links.transcript_label(tu)}]({tu})"]
        lines += ["", "### THE SIGNAL", ""]
        lines += [cite(c, best_link(ep) or ep["url"]) for c in ep["signal"]]
        if ep.get("interests"):
            lines += ["", f"**Interests to note:** {ep['interests']}"]
        for n, s in enumerate(ep["sections"], 1):
            lines += ["", f"### {n:02d} {s['title']}", "", s["body"]]
            lines += [cite(c, best_link(ep) or ep["url"]) for c in s.get("claims", [])]
    lines += ["", "_AI-assisted summaries of public episodes. Verify before relying on them. Not investment advice._"]
    return "\n".join(lines) + "\n"
