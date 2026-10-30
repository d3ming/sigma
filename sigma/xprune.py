"""Deletion sync for the X edition: a post deleted (or made protected) on X leaves everything Sigma keeps.

X's developer terms require deleting stored X content when the post is deleted on X. Sigma has no X access, so the
scanner does the lookups (skills/x-scan, step 7): Sigma writes the ids it has published in the last 30 days to
`<x dir>/check-ids.json`, the scanner asks the API about them (up to 100 ids a call) and lists the ones that no longer
exist in its manifest as `ids_gone`. `sigma x prune <date>` then removes those posts from

  published/x/editions/    the post, and every sentence that cites it (a sentence rests on its cites); a day with
                           nothing left is deleted
  published/signals/        the post's signals (sigma signals-index)
  published/x/stances/     the post's row, its id in a thread row, and the legacy sentence rows of dropped sentences
  <x dir>/scan/            the post in posts.jsonl and quoted.jsonl, on every day
  <x dir>/days/            edition.json, prep.md, links.json and the stance batches

and writes the next check-ids.json. It is the one exception to "label once": a label dies with its post.
Rerunning it for the same date changes nothing. Standard library only, like stance.py.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import date, timedelta
from pathlib import Path

from . import signals_index, events, stance, xdaily

CHECK_DAYS = 30          # a published post is checked for this many days
CHECK_BATCH = 100        # the API's limit of ids per lookup call (the scanner's batch size)
MAX_GONE_SHARE = 0.5     # more than half of the checked ids gone looks like a failed lookup, not 50% deletions
ID = re.compile(r"^\d{5,25}$")


def check_ids_path() -> Path:
    return xdaily.x_dir() / "check-ids.json"


def _read(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(p: Path, text: str) -> None:
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, p)


# ---------------------------------------------------------------- the list the scanner checks

def published_ids(published: Path, through: str, days: int = CHECK_DAYS) -> list[str]:
    """Ids in published/x/ (edition posts and cites, stance rows and their threads) for the days from `through` minus
    `days` up to `through`, sorted."""
    first = (date.fromisoformat(through) - timedelta(days=days)).isoformat()
    ids: set[str] = set()
    pub = Path(published) / "x"
    for f in sorted((pub / "editions").glob("*.json")) if (pub / "editions").is_dir() else []:
        if first <= f.stem <= through and isinstance(ed := _read(f), dict):
            ids |= {str(p["id"]) for section in ("posts", "more") for p in ed.get(section) or []
                    if isinstance(p, dict) and p.get("id")}
            ids |= {str(c) for s in ed.get("signals") or [] if isinstance(s, dict) for c in s.get("cites") or []}
    for f in sorted((pub / "stances").glob("*.jsonl")) if (pub / "stances").is_dir() else []:
        if first <= f.stem <= through:
            for r in xdaily.read_jsonl(f):
                ids |= {str(r["id"])} if r.get("id") else set()
                ids |= {str(i) for i in r.get("thread") or []}
    return sorted(i for i in ids if ID.match(i))


def write_check_ids(published: Path, through: str) -> Path:
    ids = published_ids(published, through)
    p = check_ids_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    _write(p, json.dumps({"through": through, "days": CHECK_DAYS, "ids": ids}, indent=1) + "\n")
    return p


# ---------------------------------------------------------------- removal

def _filter_lines(path: Path, drop) -> int:
    """Remove the JSONL rows `drop(row)` is true for (the other lines stay byte for byte). Returns rows removed."""
    if not path.exists():
        return 0
    lines = path.read_text(encoding="utf-8").split("\n")
    keep, n = [], 0
    for line in lines:
        if line.strip() and drop(json.loads(line)):
            n += 1
        else:
            keep.append(line)
    if n:
        _write(path, "\n".join(keep))
    return n


def drop_from_edition(ed: dict, gone: set[str]) -> tuple[dict, list[tuple[str, int, str]]]:
    """The edition without `gone` posts and without every sentence that cites one, and the dropped sentences as
    (section, index in the original, text). Works on the public edition and on days/<date>/edition.json (same shape)."""
    out, dropped = dict(ed), []
    kept = []
    for i, s in enumerate(ed.get("signals") or []):
        if gone & {str(c) for c in s.get("cites") or []}:
            dropped.append(("signals", i, s.get("text", "")))
        else:
            kept.append(s)
    if "signals" in ed:
        out["signals"] = kept
    for section in ("posts", "more"):
        if section in ed:
            out[section] = [p for p in ed[section] if str(p.get("id")) not in gone]
    return out, dropped


def _prune_editions(published: Path, gone: set[str]) -> dict:
    """Edit published/x/editions/*.json; returns {date: [legacy stance keys of the sentences dropped]} and counts."""
    res = {"editions": 0, "sentences": 0, "posts": 0, "days_removed": 0, "keys": {}, "rekeys": {}}
    d = Path(published) / "x" / "editions"
    for f in sorted(d.glob("*.json")) if d.is_dir() else []:
        ed = _read(f)
        if not isinstance(ed, dict):
            continue
        new, dropped = drop_from_edition(ed, gone)
        removed_posts = sum(len(ed.get(section) or []) - len(new.get(section) or []) for section in ("posts", "more"))
        if not dropped and not removed_posts:
            continue
        res["editions"] += 1
        res["sentences"] += len(dropped)
        res["posts"] += removed_posts
        res["keys"][f.stem] = {stance.x_key(f.stem, lens, i, text) for lens, i, text in dropped}
        dropped_indexes = {i for section, i, _ in dropped if section == "signals"}
        rekeys, next_index = {}, 0
        for i, signal in enumerate(ed.get("signals") or []):
            if i in dropped_indexes:
                continue
            old_key = stance.x_key(f.stem, "signals", i, signal.get("text", ""))
            new_key = stance.x_key(f.stem, "signals", next_index, signal.get("text", ""))
            if old_key != new_key:
                rekeys[old_key] = new_key
            next_index += 1
        if rekeys:
            res["rekeys"][f.stem] = rekeys
        if not new.get("signals") and not new.get("posts") and not new.get("more"):
            f.unlink()
            res["days_removed"] += 1
        else:
            _write(f, json.dumps(new, indent=1, ensure_ascii=False) + "\n")
    return res


def _prune_stances(published: Path, gone: set[str], keys: dict[str, set[str]], rekeys: dict[str, dict[str, str]]) -> tuple[int, set[str]]:
    """Remove the rows of gone posts, take gone ids out of thread lists, drop the legacy sentence rows in `keys`."""
    n, changed_days = 0, set()
    d = Path(published) / "x" / "stances"
    for f in sorted(d.glob("*.jsonl")) if d.is_dir() else []:
        lines, out, changed = f.read_text(encoding="utf-8").split("\n"), [], False
        dead = {"p-" + g for g in gone} | keys.get(f.stem, set())
        for line in lines:
            if not line.strip():
                out.append(line)
                continue
            r = json.loads(line)
            if str(r.get("id")) in gone or r.get("key") in dead:
                n, changed = n + 1, True
                continue
            if r.get("key") in rekeys.get(f.stem, {}):
                r["key"] = rekeys[f.stem][r["key"]]
                line, changed = json.dumps(r, ensure_ascii=False), True
            if isinstance(r.get("thread"), list) and gone & {str(i) for i in r["thread"]}:
                r["thread"] = [i for i in r["thread"] if str(i) not in gone]
                if not r["thread"]:
                    del r["thread"]
                line, changed = json.dumps(r, ensure_ascii=False), True
            out.append(line)
        if changed:
            changed_days.add(f.stem)
            if any(x.strip() for x in out):
                _write(f, "\n".join(out))
            else:
                f.unlink()
    return n, changed_days


def _prune_private(gone: set[str]) -> tuple[dict, set[str]]:
    """The scans and working files under the x dir."""
    res = {"scan_posts": 0, "days_files": 0}
    affected_days = set()
    xd = xdaily.x_dir()
    # posts that quote a gone post: their prep section and stance item carry its text as the quoted post
    quoting = {str(p["id"]) for f in xd.glob("scan/*/posts.jsonl") for p in xdaily.read_jsonl(f) if str(p.get("quoted_id")) in gone}
    for f in [*xd.glob("scan/*/posts.jsonl"), *xd.glob("scan/*/quoted.jsonl")]:
        removed = _filter_lines(f, lambda r: str(r.get("id")) in gone)
        res["scan_posts"] += removed
        if removed:
            affected_days.add(f.parent.name)
    for day in sorted(xd.glob("days/*")):
        ed = _read(day / "edition.json")
        if isinstance(ed, dict):
            new, dropped = drop_from_edition(ed, gone)
            if dropped or any(len(new.get(section) or []) != len(ed.get(section) or []) for section in ("posts", "more")):
                _write(day / "edition.json", json.dumps(new, indent=1, ensure_ascii=False) + "\n")
                res["days_files"] += 1
                affected_days.add(day.name)
        if (prep := day / "prep.md").exists():  # "## <id> @handle ..." opens a post's section
            text = prep.read_text(encoding="utf-8")
            parts = re.split(r"(?m)^(?=## \d)", text)
            kept = [p for p in parts if not (m := re.match(r"## (\d+) ", p)) or m.group(1) not in gone]
            kept = [re.sub(r"(?m)^> quoting @.*\n?", "", p) if (m := re.match(r"## (\d+) ", p)) and m.group(1) in quoting else p for p in kept]
            if "".join(kept) != text:
                _write(prep, "".join(kept))
                res["days_files"] += 1
        if isinstance(links := _read(day / "links.json"), list):
            for c in links:
                c["found_via"] = [v for v in c.get("found_via") or [] if str(v.get("post_id")) not in gone]
            kept = [c for c in links if c.get("found_via") or "found_via" not in c]
            if kept != _read(day / "links.json"):
                _write(day / "links.json", json.dumps(kept, indent=2, ensure_ascii=False) + "\n")
                res["days_files"] += 1
        for f in [*day.glob("stance/in-*.json"), *day.glob("stance/out-*.json"),
                  *day.glob("stance/merged/in-*.json"), *day.glob("stance/merged/out-*.json")]:
            rows = _read(f)
            if not isinstance(rows, list):
                continue
            kept = [r for r in rows if not (isinstance(r, dict) and (str(r.get("id")) in gone or r.get("key") in {"p-" + g for g in gone}
                                                                       or gone & {str(i) for i in [*(r.get("thread") or []), *(r.get("cites") or [])]}))]
            kept = [{k: v for k, v in r.items() if k != "quoted"} if isinstance(r, dict) and str(r.get("id")) in quoting else r for r in kept]
            if kept != rows:
                _write(f, json.dumps(kept, indent=1, ensure_ascii=False) + "\n")
                res["days_files"] += 1
    return res, affected_days


def _edition_sync_days(published: Path, gone: set[str]) -> set[str]:
    days = set()
    root = Path(published) / "x" / "editions"
    for f in sorted(root.glob("*.json")) if root.is_dir() else []:
        ed = _read(f)
        if not isinstance(ed, dict):
            continue
        new, dropped = drop_from_edition(ed, gone)
        if dropped or any(len(new.get(section) or []) != len(ed.get(section) or []) for section in ("posts", "more")):
            days.add(f.stem)
    xd = xdaily.x_dir()
    for f in [*xd.glob("scan/*/posts.jsonl"), *xd.glob("scan/*/quoted.jsonl")]:
        if any(str(row.get("id")) in gone for row in xdaily.read_jsonl(f)):
            days.add(f.parent.name)
    for day in sorted(xd.glob("days/*")):
        ed = _read(day / "edition.json")
        if isinstance(ed, dict):
            new, dropped = drop_from_edition(ed, gone)
            if dropped or any(len(new.get(section) or []) != len(ed.get(section) or []) for section in ("posts", "more")):
                days.add(day.name)
    return days


def _preflight_public_editions(published: Path, gone: set[str], days: set[str]) -> None:
    if not days:
        return
    original = xdaily.x_dir()
    with tempfile.TemporaryDirectory(prefix="sigma-x-prune-") as tmp:
        staged = Path(tmp) / "x"
        old_x_dir = os.environ.get("SIGMA_X_DIR")
        os.environ["SIGMA_X_DIR"] = str(staged)
        try:
            for day in sorted(days):
                if not xdaily.edition_path(published, day).is_file():
                    continue
                source_path = original / "days" / day / "edition.json"
                source = _read(source_path)
                if not isinstance(source, dict):
                    raise SystemExit(f"[x] cannot refresh published X edition {day}: private edition is missing or unreadable")
                source, _ = drop_from_edition(source, gone)
                real_scan, staged_scan = original / "scan" / day, staged / "scan" / day
                manifest = real_scan / "manifest.json"
                if not manifest.is_file():
                    raise SystemExit(f"[x] cannot refresh published X edition {day}: private scan is missing or unreadable")
                staged_scan.mkdir(parents=True, exist_ok=True)
                (staged_scan / "manifest.json").write_bytes(manifest.read_bytes())
                for name in ("posts.jsonl", "quoted.jsonl"):
                    real_file = real_scan / name
                    if not real_file.is_file():
                        raise SystemExit(f"[x] cannot refresh published X edition {day}: private scan is missing or unreadable")
                    kept = [row for row in xdaily.read_jsonl(real_file) if str(row.get("id")) not in gone]
                    (staged_scan / name).write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in kept), encoding="utf-8")
                try:
                    errors, _ = xdaily.edition_problems(day, source)
                    if errors:
                        raise SystemExit(f"[x] cannot refresh published X edition {day}: private edition fails its source check")
                    xdaily.public_edition(day, source)
                except (OSError, ValueError, KeyError, TypeError):
                    raise SystemExit(f"[x] cannot refresh published X edition {day}: private scan is unreadable") from None
        finally:
            if old_x_dir is None:
                os.environ.pop("SIGMA_X_DIR", None)
            else:
                os.environ["SIGMA_X_DIR"] = old_x_dir


def _sync_public_editions(published: Path, days: set[str]) -> None:
    for day in sorted(days):
        public_path = xdaily.edition_path(published, day)
        source_path = xdaily.day_dir(day) / "edition.json"
        if not public_path.exists():
            continue
        if not source_path.exists():
            raise SystemExit(f"[x] cannot refresh published X edition {day}: private edition is missing")
        source = _read(source_path)
        if not isinstance(source, dict):
            raise SystemExit(f"[x] cannot refresh published X edition {day}: private edition is unreadable")
        try:
            errors, _ = xdaily.edition_problems(day, source)
            if errors:
                raise SystemExit(f"[x] cannot refresh published X edition {day}: private edition fails its source check")
            expected = xdaily.public_edition(day, source)
        except (OSError, ValueError, KeyError, TypeError):
            raise SystemExit(f"[x] cannot refresh published X edition {day}: private scan is unreadable") from None
        if _read(public_path) != expected:
            _write(public_path, json.dumps(expected, indent=1, ensure_ascii=False) + "\n")


def gone_ids(d: str, force: bool = False) -> set[str]:
    """The ids scan d's manifest reports as no longer on X, after the sanity checks."""
    man = _read(xdaily.scan_dir(d) / "manifest.json")
    if not isinstance(man, dict):
        return set()
    gone = {str(i) for i in man.get("ids_gone") or []}
    if bad := sorted(i for i in gone if not ID.match(i)):
        raise SystemExit(f"[x] manifest ids_gone has values that are not post ids: {bad[:3]}")
    checked = man.get("ids_checked") or 0
    if gone and not force and (not checked or len(gone) > max(5, MAX_GONE_SHARE * checked)):
        raise SystemExit(f"[x] the scan reports {len(gone)} of {checked} checked ids gone; that looks like a failed lookup, not "
                         f"deletions. Ask the scanner to recheck, or rerun with --force.")
    return gone


def prune(d: str, published: Path, force: bool = False) -> dict:
    gone = gone_ids(d, force)
    res = {"gone": len(gone)}
    if gone:
        edition_days = _edition_sync_days(published, gone)
        _preflight_public_editions(Path(published), gone, edition_days)
        ed = _prune_editions(published, gone)
        res |= {k: v for k, v in ed.items() if k not in {"keys", "rekeys"}}
        res["stance_rows"], stance_days = _prune_stances(published, gone, ed["keys"], ed["rekeys"])
        private, affected_days = _prune_private(gone)
        res |= private
        edition_days |= affected_days | set(ed["keys"])
        _sync_public_editions(published, edition_days)
        res["signals_signals"] = signals_index.prune(published, gone, edition_days | stance_days)
    res["check_ids"] = len(published_ids(published, d))
    return res


def prune_cmd(args) -> None:
    res = prune(args.date, Path(args.published), args.force)
    p = write_check_ids(Path(args.published), args.date)
    events.note(gone=res["gone"], posts=res.get("posts", 0), stance_rows=res.get("stance_rows", 0), check_ids=res["check_ids"])
    man = _read(xdaily.scan_dir(args.date) / "manifest.json") or {}
    print(f"[x] prune {args.date}: scan checked {man.get('ids_checked', 'no')} ids, {res['gone']} gone"
          + (f"; removed {res['posts']} posts and {res['sentences']} sentences from {res['editions']} editions"
             f" ({res['days_removed']} days deleted), {res['stance_rows']} stance rows, {res['scan_posts']} scanned posts,"
             f" {res['days_files']} working files" if res["gone"] else ""))
    print(f"[x] next scan checks {res['check_ids']} ids ({-(-res['check_ids'] // CHECK_BATCH)} calls): {p}")
