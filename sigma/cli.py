from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import events, steplog, verify
from .config import STYLES
from .fetch import DEFAULT_AUDIO_MINUTES, daily, fetch, transcribe_run
from .paths import data_root
from .triage import DEFAULT_TOP
from .whisper import BACKEND_CHOICES

ROOT = Path(__file__).resolve().parent.parent
DATA = data_root()



def people_file() -> Path:
    return DATA / "people.yaml"

def publish(args) -> None:
    from . import ranked
    from .digest import render

    try:
        data = ranked.load(args.ranked)
        warnings = ranked.validate(data)
    except ranked.RankedError as exc:
        sys.exit(f"[publish] invalid: {exc}")
    from . import links as links_mod, report

    run_dir = Path(args.ranked).resolve().parent
    man = {}
    if (run_dir / "manifest.json").exists():
        man = {r["episode_id"]: r for r in json.loads((run_dir / "manifest.json").read_text()).get("episodes", [])}
        for e in data["episodes"]:
            if not e.get("transcript_url") and (u := links_mod.transcript_link(man.get(e["episode_id"], {}))):
                e["transcript_url"] = u
    errors, grounding = report.ranked_verify(data, run_dir)
    for w in warnings + grounding:
        print(f"[publish] warning: {w}")
    errors += grounding
    if errors:
        sys.exit("\n".join(f"[publish] invalid: {e}" for e in errors))
    from . import themes

    if (run_dir / themes.FILE).exists():
        _, theme_errors, theme_warnings = themes.check_run(run_dir, data, args.top)
        for w in theme_warnings:
            print(f"[publish] warning: {w}")
        theme_errors += theme_warnings
        if theme_errors:
            sys.exit("\n".join(f"[publish] invalid: {e}" for e in theme_errors))
        print(f"[publish] {themes.FILE} ok")
    from . import published

    try:
        published.validate_claim_inputs(run_dir)
    except Exception as exc:
        sys.exit(f"[publish] invalid: {exc}")
    from . import showlinks

    shows = showlinks.by_name(DATA / "show_links.yaml")
    for rank, old_url, new_url in links_mod.episode_urls(data["episodes"][:args.top] if args.top else data["episodes"], shows, man):
        print(f"[publish] #{rank} link: {old_url or '(none)'} -> {new_url}")
    md = render(data, top_claims=args.top_claims, top=args.top, show_links=shows)
    out = Path(args.out or Path(args.ranked).with_name(f"digest-{data['week_of']}.md"))
    out.write_text(md)
    print(f"[publish] {out}")
    after_stage(run_dir, ingest=True, top=args.top)


def after_stage(run_dir: Path, ingest: bool = False, top: int | None = None) -> None:
    """Bookkeeping code can do for the agent: stamp stage timings, and load a finished run into the library.
    `top` is the weekly digest's top N, which themes.json evidence must sit in. Never fails the command that called it."""
    from . import status

    try:
        if done := status.record_boundaries(run_dir):
            print(f"[timing] recorded {', '.join(done)}")
    except Exception as exc:
        print(f"[timing] warning: could not record stage times: {type(exc).__name__}: {exc}")
    if ingest and not os.environ.get("SIGMA_NO_PUBLISHED"):
        from . import published

        try:
            dest, files = published.export(run_dir, top=top)
            rel = dest.relative_to(ROOT) if dest.is_relative_to(ROOT) else dest
            print(f"[published] {rel}: {', '.join(files)}")
        except Exception as exc:
            events.note(export_failed=1)
            sys.exit(f"[published] invalid: not exported ({type(exc).__name__}: {exc})")
    if ingest:
        from . import published

        try:
            published.validate_claim_inputs(run_dir)
        except Exception as exc:
            sys.exit(f"[library] invalid: not ingested ({type(exc).__name__}: {exc})")
    if ingest and not os.environ.get("SIGMA_NO_LIBRARY"):
        from . import library

        try:
            r = library.ingest_run(run_dir)
            print(f"[library] {run_dir.name}: {r.get('claims', 0)} claims, {r.get('episodes', 0)} episodes")
            events.note(claims=r.get("claims", 0), episodes=r.get("episodes", 0))
        except Exception as exc:
            events.note(library_failed=1)
            print(f"[library] warning: not ingested ({type(exc).__name__}: {exc}); run sigma library ingest {run_dir}")


KINDS = ("selected", "report")


def infer_kind(path: str) -> str:
    name = Path(path).name.lower()
    for k in KINDS:
        if name.startswith(k):
            return k
    sys.exit(f"[check] cannot infer schema from {name!r}; pass one of {', '.join(KINDS)} (e.g. check selected {path})")


def check(args) -> None:
    from . import ranked, report

    kind = args.kind
    if args.file is None:  # one positional given: it is the file
        kind, args.file = None, args.kind
    kind = kind or infer_kind(args.file)
    if kind not in KINDS:
        sys.exit(f"[check] unknown schema {kind!r}; use one of {', '.join(KINDS)}")
    try:
        data = report.validate(json.loads(Path(args.file).read_text()), kind)
    except ranked.RankedError as exc:
        sys.exit(f"[check] invalid: {exc}")
    run_dir = Path(args.file).resolve().parent
    warnings = report.warn(kind, data, run_dir)
    if args.captions:
        if kind == "report":
            warnings += report.caption_warn(data, run_dir)
        else:
            warnings.append("--captions only applies to report.json; ignored")
    for w in report.dedupe_warnings(warnings):
        print(f"[check] warning: {w}")
    if errors := report.verify(kind, data, Path(args.file).resolve().parent):
        sys.exit("\n".join(f"[check] invalid: {e}" for e in errors))
    print(f"[check] {args.file} ok")
    if kind == "selected":
        after_stage(run_dir)


def mark(args) -> None:
    from .timing import mark as do_mark

    t = do_mark(Path(args.run), args.stage, args.event)["timing"]
    print(f"[mark] {args.stage} {args.event} {t[args.stage][args.event]}" + (f" ({t[args.stage]['seconds']} s)" if args.event == "end" and "seconds" in t[args.stage] else ""))


def stats(args) -> None:
    from .timing import stats as table

    print(table(Path(args.runs)), end="")


def links(args) -> None:
    from . import ranked, report
    from .links import fill

    if args.published:
        from . import published

        try:
            r = published.relink(Path(args.run), name=args.name)
        except FileNotFoundError as exc:
            sys.exit(f"[links] {exc}")
        print(f"[links] published/{args.name or Path(args.run).resolve().name}: {r['episodes']} episodes listed, "
              f"without a link {r['before']} -> {r['after']}")
        return
    sel_p = Path(args.run) / "selected.json"
    if not sel_p.exists():
        sys.exit(f"[links] no selected.json in {args.run}")
    try:
        data = report.validate(json.loads(sel_p.read_text()), "selected")
    except ranked.RankedError as exc:
        sys.exit(f"[links] invalid: {exc}")
    if errors := report.verify("selected", data, Path(args.run)):
        sys.exit("\n".join(f"[links] invalid: {e}" for e in errors))
    found = fill(Path(args.run), DATA / "sources.yaml", ytsearch=args.ytsearch, show_links=DATA / "show_links.yaml")
    for eid, (yt, lu) in found.items():
        print(f"[links] {eid} youtube={yt or '-'} listen={lu or '-'}")
    events.note(picks=len(found), with_youtube=sum(bool(yt) for yt, _ in found.values()),
                no_link=sum(not (yt or lu) for yt, lu in found.values()))


def transcript_links_cmd(args) -> None:
    from .links import backfill_transcript_urls

    r = backfill_transcript_urls(Path(args.run), Path(args.sources))
    print(f"[transcript-links] {r['found']} of {r['missing']} publisher transcripts linked in {args.run}")


def export_published(args) -> None:
    from . import published
    from .themes import ThemesError

    try:
        dest, files = published.export(Path(args.run), name=args.name, top=args.top)
    except FileNotFoundError as exc:
        sys.exit(f"[published] {exc}")
    except ThemesError as exc:
        sys.exit("\n".join(f"[published] invalid: {e}" for e in str(exc).splitlines()))
    print(f"[published] {dest}: {', '.join(files)}")


def dedupe_published(args) -> None:
    from . import published

    res = published.dedupe_claims(names=args.names or None, write=not args.dry_run)
    for name, r in res.items():
        print(f"[dedupe] published/{name}: {r['before']} claims -> {r['after']}" + (" (dry run)" if args.dry_run else ""))
        for eid, e in r["episodes"].items():
            print(f"[dedupe]   {e['removed']} removed: {(e['title'] or eid)[:70]}")


def check_claims(args) -> None:
    from . import published

    problems = published.check_claims()
    if problems:
        sys.exit("\n".join(f"[check-claims] {m}" for m in problems) + f"\n[check-claims] {len(problems)} restated; `sigma dedupe-published` merges them")
    print("[check-claims] every published claims file lists each point once")


def themes_check(args) -> None:
    from . import themes

    try:
        _, errors, warnings = themes.check_run(args.run, top=args.top)
    except FileNotFoundError as exc:
        sys.exit(f"[themes-check] {exc}; write it with prompts/themes.md")
    for w in warnings:
        print(f"[themes-check] warning: {w}")
    if errors:
        sys.exit("\n".join(f"[themes-check] invalid: {e}" for e in errors))
    print(f"[themes-check] {Path(args.run) / themes.FILE} ok (evidence inside the top {args.top})")


def rank_prep(args) -> None:
    from .rank import prep

    r = prep(Path(args.run), args.batches, rescore=args.rescore, eval_n=args.eval)
    print(f"[rank-prep] {r['to_score']} of {r['transcribed']} transcribed episodes to score in {r['batches']} batches under "
          f"{args.run}/rank; {r['stored']} keep their stored score ({r['without_transcript']} without a transcript are not "
          f"scored)." + (f" rank/eval-in.json: {r['eval']} stored episodes to re-score blind." if r["eval"] else "")
          + (f" {r['influencer_to_score']} of {r['influencer']} influencer episodes to score in {r['influencer_batches']} rank/influencer-N-in.json "
             f"batches (prompts/rank-influencer.md); {r['influencer_stored']} keep their stored score." if r["influencer"] else "")
          + " Give each file to a reader (prompts/rank.md); save its output as rank/<name>-out.json, then run rank-merge.")


def stance_cmd(args) -> None:
    from . import stance

    try:
        if args.cmd == "stance-prep":
            r = stance.prep(args.run, args.x, Path(args.published), args.batch)
            events.note(items=r["items"], to_label=r["to_label"], batches=r["batches"], labelled=r["labelled"])
            print(f"[stance-prep] {r['label']}: {r['to_label']} of {r['items']} items to label"
                  + (f" and {r['market_only']} labelled ones to read for market targets only" if r["market_only"] else "")
                  + f" in {r['batches']} batches under {r['folder']}; {r['labelled']} already labelled. "
                  f"Give each in-N.json to a reader (prompts/stance.md); "
                  f"save its output as out-N.json, then run stance-merge.")
        else:
            r = stance.merge(args.run, args.x, Path(args.published))
            events.note(added=r["added"], labels=r["labels"], kept=r["kept"], left=r["left"])
            print(f"[stance-merge] {r['label']}: {r['added']} items added ({r['labels']} labels) to {r['dest']}, "
                  f"{r['kept']} already labelled and kept; {r['left']} items still unlabelled."
                  + (f" {r['threads']} threads recorded over posts labelled one by one." if r.get("threads") else ""))
    except stance.StanceError as exc:
        sys.exit("\n".join(f"[{args.cmd}] {line}" for line in str(exc).splitlines()))


def tickers_refresh_cmd(args) -> None:
    from . import tickers

    tickers.refresh_cmd(args)


def score_eval_cmd(args) -> None:
    from . import scoreeval

    flow = Path(args.flow)
    if args.eval_cmd == "pool":
        rows = scoreeval.pool(args.db)
        print(json.dumps(rows, indent=1, ensure_ascii=False) if args.json else
              "\n".join(f"{r['score']}  t{r['tier']}  {r['episode_id']}  {r['show']}: {r['title'][:70]}" for r in rows))
    elif args.eval_cmd == "prep":
        r = scoreeval.prep(flow, args.variant, Path(args.rubric), args.reps, args.size)
        print(f"[score-eval] {r['variant']}: {r['episodes']} gold episodes x {r['reps']} reps in {r['batches']} batches "
              f"under {flow / r['variant']}/in. Give each file to a fresh reader (the variant's rubric.md); save its output "
              f"as out/<name>-out.json, then run grade.")
    elif args.eval_cmd == "grade":
        s = scoreeval.grade(flow, args.variant)
        for p in s["problems"]:
            print(f"[score-eval] {p}")
        print(scoreeval.table(flow))
    else:
        print(scoreeval.table(flow))


def rank_merge(args) -> None:
    from . import ranked, status
    from .rank import INFLUENCER_FILE, merge

    run = Path(args.run)
    man = json.loads((run / "manifest.json").read_text()) if (run / "manifest.json").exists() else {}
    target = args.out or ("ranked.json" if man.get("kind") == "custom" or status.is_weekly(run, man) else "scores.json")
    try:
        data = merge(run, args.ranked_by, args.week_of, ranking=target == "ranked.json")
        warnings = ranked.validate(data, ranking=target == "ranked.json")
    except (ValueError, ranked.RankedError, FileNotFoundError) as exc:
        sys.exit(f"[rank-merge] {exc}")
    for w in warnings:
        print(f"[rank-merge] warning: {w}")
    out = run / target
    # A special issue's hand-added title and issue date survive a re-merge: losing them once listed a custom set as a weekly
    # dated by its oldest episode (2026-10-26).
    try:
        prev = json.loads(out.read_text()) if out.exists() else {}
    except ValueError:
        prev = {}
    if prev.get("title") and "title" not in data:
        data = {**data, "title": prev["title"], **({} if args.week_of else {"week_of": prev.get("week_of") or data["week_of"]})}
    out.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    print(f"[rank-merge] {out} ({len(data['episodes'])} episodes)."
          + (f" Next: sigma publish {out} --top 15" if target == "ranked.json" else " Next: sigma status " + args.run))
    events.note(scored=len(data["episodes"]))
    rank_dir = run / "rank"
    if any(rank_dir.glob("influencer-*-in.json")) or (rank_dir / "influencer-stored.json").exists():
        try:  # influencer episodes are scored under their own rubric and never enter the interview list above
            idata = merge(run, args.ranked_by, args.week_of, ranking=False, influencer=True)
            ranked.validate(idata, ranking=False)
        except (ValueError, ranked.RankedError, FileNotFoundError) as exc:
            sys.exit(f"[rank-merge] influencer: {exc}")
        (run / INFLUENCER_FILE).write_text(json.dumps(idata, indent=1, ensure_ascii=False) + "\n")
        print(f"[rank-merge] {run / INFLUENCER_FILE} ({len(idata['episodes'])} influencer episodes, scored apart from the ranking)")
    if os.environ.get("SIGMA_NO_LIBRARY"):
        return
    from . import library

    try:  # store the scores now, so a later run reuses them instead of reading the episodes again
        events.note(stored=library.ingest_run(run).get("episodes", 0))
        ev = run / "rank" / "eval-out.json"
        if ev.exists():
            d = library.record_eval(json.loads(ev.read_text()), run.name)
            (run / "rank" / "eval.json").write_text(json.dumps(d, indent=1) + "\n")
            events.note(eval_n=d.get("n", 0), eval_mean_abs=d.get("mean_abs", 0), eval_crossed=d.get("crossed", 0))
            print(f"[eval] {d.get('n', 0)} stored episodes re-scored blind: mean change {d.get('mean', 0):+}, "
                  f"mean absolute {d.get('mean_abs', 0)}, {d.get('within_1', 0)} within 1 point, "
                  f"{d.get('crossed', 0)} crossed the 6 bar. Stored scores are unchanged.")
    except Exception as exc:
        print(f"[library] warning: scores not stored ({type(exc).__name__}: {exc}); run sigma library ingest {run}")


def show_links(args) -> None:
    from . import showlinks

    path = Path(args.file)
    if args.fix and not args.verify:
        sys.exit("[show-links] --fix needs --verify")
    if args.verify:
        results = showlinks.verify(Path(args.sources), path, set(args.only.split(",")) if args.only else None, pause=1.0)
        print(f"{'show':<24} {'field':<8} {'status':<12} evidence")
        for r in results:
            print(f"{r['id'][:24]:<24} {r['field']:<8} {r['status']:<12} {r['evidence']}")
        counts = {st: sum(r["status"] == st for r in results) for st in ("ok", "mismatch", "unreachable")}
        print(f"[show-links] verify: {counts['ok']} ok, {counts['mismatch']} mismatch, {counts['unreachable']} unreachable")
        if args.fix:
            for r in showlinks.apply_fix(path, results):
                print(f"[show-links] blanked {r['id']}.{r['field']} (was {r['value']})")
        elif counts["mismatch"]:
            print("[show-links] nothing edited; rerun with --fix to blank the mismatches")
        return
    changed = showlinks.fill(Path(args.sources), path, set(args.only.split(",")) if args.only else None,
                              ytsearch=args.ytsearch, websearch=args.websearch)
    data = showlinks.load(path)
    for sid, got in changed.items():
        missing = [f for f in showlinks.FIELDS if not data[sid][f]]
        print(f"[show-links] {sid}: filled {', '.join(got) or '-'}; still blank {', '.join(missing) or '-'}")
    print(f"[show-links] {path} ({len(data)} shows). Edit any value to correct it; filled values are never overwritten.")


def render_report(args) -> None:
    from . import ranked, report

    try:
        data = json.loads(Path(args.report).read_text())
        report.attach_links(data, Path(args.report).parent)
        data = report.validate(data, "report")
    except ranked.RankedError as exc:
        sys.exit(f"[report] invalid: {exc}")
    if errors := report.verify("report", data, Path(args.report).resolve().parent):
        sys.exit("\n".join(f"[report] invalid: {e}" for e in errors))
    warnings = report.warn("report", data, Path(args.report).resolve().parent)
    if warnings:
        sys.exit("\n".join(f"[report] invalid: {w}" for w in warnings))
    from . import published

    try:
        published.validate_claim_inputs(Path(args.report).resolve().parent)
    except Exception as exc:
        sys.exit(f"[report] invalid: {exc}")
    out = Path(args.out or Path(args.report).with_name("report.md"))
    out.write_text(report.render(data))
    print(f"[report] {out}")
    after_stage(Path(args.report).resolve().parent, ingest=True)


def find_cmd(args) -> None:
    from datetime import datetime, timezone

    from . import custom
    from .people import Person, load_people

    if not (args.person or args.query):
        sys.exit("[find] give at least one --person or --query")
    if args.role and not args.person:
        sys.exit("[find] --role goes with --person")
    known = {p.name.lower(): p for p in load_people(args.people)} if args.people and Path(args.people).exists() else {}
    people = [known.get(n.lower()) or Person(name=n, role=args.role or "", priority="watch", context=args.context or [])
              for n in args.person or []]
    if args.role or args.context:  # explicit flags win over the people.yaml entry
        people = [Person(**{**vars(p), **({"role": args.role} if args.role else {}),
                            **({"context": args.context} if args.context else {})}) for p in people]
    cands, errors = custom.search(people, args.query or [], datetime.now(timezone.utc), args.days, args.youtube, args.min_minutes)
    custom.mark_transcribed(cands, Path(args.runs))
    for e in errors:
        print(f"[find] warning: {e}", file=sys.stderr)
    if args.json:
        print(json.dumps(cands, indent=1, ensure_ascii=False))
    else:
        for c in cands:
            print(custom.line(c))
    free = sum(1 for c in cands if c["transcribed"])
    print(f"[find] {len(cands)} candidate(s) in the last {args.days} days, {free} already transcribed in {args.runs}"
          + (f"; {len(errors)} search(es) failed" if errors else ""), file=sys.stderr)


def custom_run_cmd(args) -> None:
    from . import custom, status as st

    run_dir = Path(args.runs) / args.name
    r = custom.build_run(run_dir, custom.load_picks(args.picks), args.note, args.sources)
    n = len(json.loads((run_dir / "manifest.json").read_text())["episodes"])
    print(f"[custom-run] {run_dir}: +{r['added']} new ({r['reused']} reused a transcript from another run, "
          f"{len(r['skipped'])} already there), {n} episodes in total")
    arg = str(run_dir)
    print(f"[custom-run] next: transcribe the rest (all picks, no triage), detached:\n  {st.restart_command(arg)}\n"
          f"  then check progress with: sigma status {arg}")


def status_cmd(args) -> None:
    from . import status as st

    run = Path(args.run)
    info = st.inspect_run(run, arg=getattr(args, "label", None) or args.run, weekly=True if args.weekly else None)
    if args.record:
        info["recorded"] = st.record_boundaries(run, info)
        st.log_stage(info)
    if args.json:
        print(json.dumps(info, indent=2, ensure_ascii=False))
    else:
        print(st.render_text(info))
        if info.get("recorded"):
            print(f"[status] recorded timing: {', '.join(info['recorded'])}")


def today_name(now=None) -> str:
    """Today's run name in the machine's local timezone."""
    from datetime import datetime

    return (now or datetime.now().astimezone()).strftime("%Y-%m-%d")


def today_cmd(args) -> None:
    name = args.run_name or today_name()
    run_dir = Path(args.runs) / name
    if not (run_dir / "manifest.json").exists():
        print(f"[today] no run {run_dir}; starting daily")
        main(["daily", "--hours", str(args.hours), "--run-name", name, "--runs", str(args.runs)])
    label = f"data/runs/{name}" if Path(args.runs).resolve() == ROOT / "data" / "runs" else str(run_dir)
    status_cmd(argparse.Namespace(run=str(run_dir), label=label, weekly=False, record=True, json=args.json))


def doctor_cmd(args) -> None:
    from . import doctor

    rows = doctor.run_checks()
    for level, name, msg in rows:
        print(f"[doctor] {level:<4} {name}: {msg}")
    fails = sum(1 for r in rows if r[0] == "fail")
    print(f"[doctor] {len(rows) - fails - sum(1 for r in rows if r[0] == 'warn')} ok, "
          f"{sum(1 for r in rows if r[0] == 'warn')} warn, {fails} fail")
    if fails:
        sys.exit(1)


def step_cmd(args) -> None:
    if code := steplog.step_cmd(args):
        sys.exit(code)


def x_cmd(args) -> None:
    from . import xdaily

    from . import xlinks, xprune

    {"status": xdaily.status_cmd, "scan-check": xdaily.scan_check_cmd, "prep": xdaily.prep_cmd, "check": xdaily.check_cmd,
     "publish": xdaily.publish_cmd, "heartbeat": xdaily.heartbeat_cmd, "health": xdaily.health_cmd, "links": xlinks.links_cmd, "prune": xprune.prune_cmd}[args.x_cmd](args)


def source_cmd(args) -> None:
    from . import sources

    (sources.add_cmd if args.src_cmd == "add" else sources.review_cmd)(args)


def calls_cmd(args) -> None:
    from . import calls

    calls.calls_cmd(args)


def entities_cmd(args) -> None:
    from . import entities

    (entities.check_cmd if args.ent_cmd == "check" else entities.backfill_cmd)(args)


def library_cmd(args) -> None:
    from . import library

    db = args.db or library.DEFAULT_DB
    if args.lib_cmd != "ingest" and not Path(db).exists():
        sys.exit(f"[library] no library at {db}; run sigma library ingest runs/<name> (or --all) first")
    if args.lib_cmd == "ingest":
        dirs = library.run_dirs(args.runs) if args.all else [Path(r) for r in args.run]
        if not dirs:
            sys.exit("[library] no run folders given (pass runs/<name> or --all)")
        for d in dirs:
            try:
                from . import published

                published.validate_claim_inputs(d)
                r = library.ingest_run(d, db, transcripts=not args.no_transcripts)
            except FileNotFoundError as exc:
                sys.exit(f"[library] {exc}")
            except Exception as exc:
                sys.exit(f"[library] invalid: {exc}")
            print(f"[library] {r['run']}: {r['episodes']} episodes, {r['claims']} claims, {r['chunks']} transcript chunks -> {db}")
    elif args.lib_cmd == "query":
        try:
            if args.transcripts:
                if not args.text:
                    sys.exit("[library] --transcripts needs --text")
                rows = library.search_transcripts(db, args.text, args.since, args.until, args.person, args.limit, args.show)
            else:
                rows = library.query_claims(db, args.ticker, args.person, args.text, args.since, args.until, args.limit, args.show)
        except ValueError as exc:
            sys.exit(f"[library] {exc}")
        if args.json:
            print(json.dumps(rows, indent=1, ensure_ascii=False))
            return
        for r in rows:
            mm, ss = divmod(int(r["timestamp"] or 0), 60)
            if args.transcripts:
                body = f"[{mm}:{ss:02d}] {r['snippet']}"
            else:
                body = f"{r['speaker'] or 'unknown'} [{mm}:{ss:02d}] {r['text']}" + (f" ({', '.join(r['tickers'])})" if r["tickers"] else "")
            print(f"{r['published']} | {r['show']} | {r['title']}\n  {body}\n  {r['link']}")
        print(f"[library] {len(rows)} result(s)", file=sys.stderr)
    elif args.lib_cmd == "export":
        if args.out:
            with open(args.out, "w") as fh:
                n = library.export_jsonl(db, fh, args.since, args.until)
            print(f"[library] {n} claims -> {args.out}")
        else:
            library.export_jsonl(db, sys.stdout, args.since, args.until)
    else:
        print(json.dumps(library.stats(db), indent=1))


def run_date(value: str, today=None) -> str:
    from datetime import date, timedelta

    today = today or date.today()
    if value == "yesterday":
        return (today - timedelta(days=1)).isoformat()
    if value == "today":
        return today.isoformat()
    return date.fromisoformat(value).isoformat()


def add_fetch_args(f) -> None:
    f.add_argument("--sources", default=str(DATA / "sources.yaml"))
    f.add_argument("--db", default=str(DATA / "podcast_signals.sqlite"))
    f.add_argument("--runs", default=str(DATA / "runs"))
    f.add_argument("--only", help="comma-separated source ids")
    f.add_argument("--per-source", type=int, default=6, help="episodes kept per source in the window; the rest are listed in manifest sources.<id>.capped")
    f.add_argument("--people", default=str(people_file()), help="people watchlist; empty string disables")
    f.add_argument("--per-person", type=int, default=3)
    f.add_argument("--run-name", help="run folder name (default: today's date)")
    f.add_argument("--whisper-minutes", type=float, help="whisper minutes inside fetch (default 0; transcribe does the whispering)")
    f.add_argument("--whisper-per-episode", type=float, help="cap per episode in minutes (default: whole episode)")
    f.add_argument("--refetch", action="store_true", help="include episodes already in the dedupe DB")
    f.add_argument("--min-transcript-chars", type=int, default=5000, help="shorter text is flagged fallback, not a transcript")
    f.add_argument("--include-reruns", action="store_true", help="keep replays and re-airs")
    f.add_argument("--youtube-mirror", action="store_true",
                   help="for episodes without a feed transcript, search YouTube for the same episode and use its captions "
                        "(Mac/residential IP only; runs before whisper; for a machine where Whisper is slow, since the Mac "
                        "transcribes podcast audio first)")


def other_worktree(cwd: Path) -> Path | None:
    """The git worktree of this repository that `cwd` is in, when it is not the checkout this code runs from. The venv's
    `sigma` script always runs the main checkout, so in a worktree it tests the wrong code and writes the real data (a
    worker started a live daily run that way, 2026-10-27)."""
    for d in (cwd, *cwd.parents):
        if (d / ".git").exists():
            if d.resolve() == ROOT or not (d / ".git").is_file():
                return None
            gitdir = (d / ".git").read_text(encoding="utf-8", errors="replace")
            return d if str(ROOT / ".git" / "worktrees") in gitdir else None
    return None


def main(argv=None):
    if (argv := sys.argv[1:] if argv is None else list(argv))[:1] == ["event"]:
        return events.event_main(argv[1:])  # before the wrapper and the main parser: it must never fail or log itself
    return events.run_command(_main, argv)  # one event per command; the result, exit and output stay the command's own


def _main(argv=None):
    ap = argparse.ArgumentParser(prog="sigma")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="ingest episodes and write transcripts plus manifest.json to a run folder")
    f.add_argument("--days", type=int, default=7)
    add_fetch_args(f)
    t = sub.add_parser("transcribe", help="whisper untranscribed episodes in a run folder; resumable, run it detached")
    t.add_argument("run")
    t.add_argument("--minutes", type=float, default=DEFAULT_AUDIO_MINUTES,
                   help="source-audio minutes to transcribe (default: 3600; not wall-clock time)")
    t.add_argument("--per-episode", type=float)
    t.add_argument("--db", help="also record transcript_source in this SQLite DB")
    t.add_argument("--force", action="store_true", help="ignore a stale transcribe.lock")
    t.add_argument("--retry-errors", action="store_true", help="retry episodes that failed before")
    t.add_argument("--include-reruns", action="store_true")
    t.add_argument("--min-transcript-chars", type=int, default=5000)
    t.add_argument("--news", action="store_true", help="also whisper news/market-recap shows, last (default: skip them)")
    t.add_argument("--top", type=int, default=DEFAULT_TOP, help="triage: whisper only the top N by metadata score, plus core people (0 = all)")
    t.add_argument("--no-tier1-floor", action="store_true",
                   help="triage: do not also whisper every non-news, non-rerun tier-1 episode")
    t.add_argument("--people", default=str(people_file()))
    t.add_argument("--retriage", action="store_true", help="recompute triage even if the manifest already has it")
    fd = sub.add_parser("find", help="search iTunes and YouTube for candidate episodes (people and/or free text); creates no run")
    fd.add_argument("--person", action="append", help="person to look for; repeatable (people.yaml aliases and context apply)")
    fd.add_argument("--role", help="the --person's role, shown in the output")
    fd.add_argument("--context", action="append", help="for common names: a hit must mention one of these words; repeatable")
    fd.add_argument("--query", action="append", help="free-text episode search, e.g. a company name; repeatable")
    fd.add_argument("--days", type=int, default=30)
    fd.add_argument("--youtube", action=argparse.BooleanOptionalAction, default=True,
                    help="also search YouTube (default on; needs a residential IP, a block just yields no YouTube hits)")
    fd.add_argument("--min-minutes", type=int, default=20, help="drop anything shorter (default 20)")
    fd.add_argument("--json", action="store_true", help="a list of candidates that `custom-run --picks` reads as is")
    fd.add_argument("--people", default=str(people_file()))
    fd.add_argument("--runs", default=str(DATA / "runs"), help="run folders searched for transcripts already made")
    cr = sub.add_parser("custom-run", help="build a run from a JSON list of chosen candidates (`find --json`); does not transcribe")
    cr.add_argument("name", help="run folder name under --runs")
    cr.add_argument("--picks", required=True, help="JSON list of candidates, as `find --json` prints them (filtered by the agent)")
    cr.add_argument("--note", help="why this run exists; stored in the manifest")
    cr.add_argument("--runs", default=str(DATA / "runs"))
    cr.add_argument("--sources", default=str(DATA / "sources.yaml"), help="gives a pick the tier of its show (empty string: tier 2)")
    d = sub.add_parser("daily", help="people first, then channels, for the last --hours; queues transcribe in the background")
    add_fetch_args(d)
    d.add_argument("--hours", type=float, default=72)
    d.add_argument("--minutes", type=float, default=DEFAULT_AUDIO_MINUTES,
                   help="source-audio minutes for the queued transcribe (default: 3600; not wall-clock time)")
    d.add_argument("--no-transcribe", action="store_true")
    d.add_argument("--news", action="store_true", help="queued transcribe also whispers news shows, last (default: skip)")
    d.add_argument("--top", type=int, default=DEFAULT_TOP, help="queued transcribe whispers only the top N by triage score, plus core people")
    d.add_argument("--no-tier1-floor", action="store_true", help="queued transcribe: no extra whisper floor for tier-1 episodes")
    c = sub.add_parser("check", help="validate selected.json or report.json")
    c.add_argument("kind", help="selected|report, or just the file (schema inferred from selected*.json / report*.json)")
    c.add_argument("file", nargs="?")
    c.add_argument("--captions", action="store_true",
                   help="report only, network: compare cite numbers/timestamps with the linked YouTube video's captions")
    r = sub.add_parser("report", help="validate report.json, render report.md and export data/published/<run>/")
    r.add_argument("report")
    r.add_argument("--out")
    lk = sub.add_parser("links", help="resolve youtube_url (verified) and listen_url (Apple/Spotify/episode page) into selected.json")
    lk.add_argument("run")
    lk.add_argument("--ytsearch", action="store_true",
                    help="last resort when no YouTube video was found: yt-dlp ytsearch5 (run from a Mac/residential IP; results still oEmbed-verified)")
    lk.add_argument("--published", action="store_true",
                    help="instead: look links up for every published episode of the run (not only the picks) and update published/<run>/ in place; no selected.json needed")
    lk.add_argument("--name", help="with --published: the folder under data/published/ (default: the run folder's name)")
    tl = sub.add_parser("transcript-links", help="record the hosted transcript URL for older manifests (re-reads the feeds)")
    tl.add_argument("run")
    tl.add_argument("--sources", default=str(DATA / "sources.yaml"))
    ep = sub.add_parser("export-published", help="copy a run's report/ranking outputs into data/published/<run>")
    ep.add_argument("run")
    ep.add_argument("--name", help="folder name under data/published/ (default: the run folder's name)")
    ep.add_argument("--top", type=int, default=15, help="themes.json only: the digest's top N its evidence must sit in")
    dp = sub.add_parser("dedupe-published", help="collapse restated claims in data/published/<run>/claims.jsonl, in place (a new export does it already)")
    dp.add_argument("names", nargs="*", help="folders under data/published/ (default: all)")
    dp.add_argument("--dry-run", action="store_true", help="report what would go; write nothing")
    sub.add_parser("check-claims", help="fail when an exported claims file lists the same point twice")
    sx = sub.add_parser("search-index", help="export the library's transcript index, minus no_search shows, for the site's search; --upload puts it in the private Blob store")
    sx.add_argument("--library", default=str(DATA / "library.sqlite"), help="the library to copy from (read only; `sigma library ingest` fills it)")
    sx.add_argument("--out", default=str(DATA / "search-index.sqlite"), help="index file to write")
    sx.add_argument("--upload", action="store_true", help="then upload it to the private Blob store; needs SEARCH_READ_WRITE_TOKEN (environment or .env.local)")
    rp = sub.add_parser("rank-prep", help="condense transcripts the library has not scored and split them into reader batches")
    rp.add_argument("run")
    rp.add_argument("--batches", type=int, default=4)
    rp.add_argument("--rescore", action="store_true", help="score every episode again, ignoring stored scores")
    rp.add_argument("--eval", type=int, default=0, metavar="N", help="also write rank/eval-in.json: N stored episodes to re-score blind")
    rm = sub.add_parser("rank-merge", help="merge reader outputs and stored scores into scores.json (daily) or ranked.json")
    rm.add_argument("run")
    rm.add_argument("--out", choices=["scores.json", "ranked.json"], help="default: ranked.json for weekly and custom runs")
    rm.add_argument("--ranked-by", default="Claude")
    rm.add_argument("--week-of", help="YYYY-MM-DD (default: earliest published date in the run)")
    from .stance import BATCH

    sp = sub.add_parser("stance-prep", help="batch the claims (or the posts of an X day) that have no stance label yet for reader agents")
    sm = sub.add_parser("stance-merge", help="check the readers' stance labels and append them to data/published/")
    for q in (sp, sm):
        q.add_argument("run", nargs="?", help="run folder, e.g. data/runs/2026-10-26 (its claims come from data/published/<run>/)")
        q.add_argument("--x", metavar="DATE", help="label the scanned X posts of DATE instead of a run")
        q.add_argument("--published", default=str(DATA / "published"))
    sp.add_argument("--batch", type=int, default=BATCH, help="most items per reader file")
    ai = sub.add_parser("signals-index", help="write data/published/signals/<date>.json and index.json: every Signals signal of the day (schema/signals-index.schema.json); never waits, names what is missing")
    ai.add_argument("date", nargs="?", help="the Pacific day, YYYY-MM-DD")
    ai.add_argument("--all", action="store_true", help="rebuild every day already in data/published/signals/ (after a prune of an earlier day)")
    ai.add_argument("--published", default=str(DATA / "published"))
    tr = sub.add_parser("tickers-refresh", help="rebuild us-tickers.json (NYSE, Nasdaq, NYSE American, Cboe) from the SEC's list")
    tr.add_argument("--contact", help="contact address for the SEC's User-Agent (env SIGMA_SEC_CONTACT); never committed")
    tr.add_argument("--out", default=str(ROOT / "us-tickers.json"))
    se = sub.add_parser("score-eval", help="grade the scoring rubric against the gold set (see .claude/skills/score-eval)")
    ssub = se.add_subparsers(dest="eval_cmd", required=True)
    sflow = argparse.ArgumentParser(add_help=False)
    sflow.add_argument("--flow", default=str(DATA / "score-eval"), help="eval folder (gold.jsonl, pairs.jsonl, variants)")
    spo = ssub.add_parser("pool", parents=[sflow], help="library episodes with a stored score and a transcript: gold candidates")
    spo.add_argument("--db")
    spo.add_argument("--json", action="store_true")
    spp = ssub.add_parser("prep", parents=[sflow], help="write blind reader batches of every gold episode for one variant")
    spp.add_argument("variant", help="baseline, v1, v2, ...")
    spp.add_argument("--rubric", default=str(ROOT / "prompts" / "rank.md"))
    spp.add_argument("--reps", type=int, default=2)
    spp.add_argument("--size", type=int, default=6, help="episodes per batch")
    sgr = ssub.add_parser("grade", parents=[sflow], help="grade a variant's reader outputs and print the status table")
    sgr.add_argument("variant")
    ssub.add_parser("table", parents=[sflow], help="status table over every graded variant")
    tc = sub.add_parser("themes-check", help="weekly: validate <run>/themes.json against ranked.json and the transcripts")
    tc.add_argument("run")
    tc.add_argument("--top", type=int, default=15, help="evidence must come from the top N ranked episodes (the digest's --top)")
    sl = sub.add_parser("show-links", help="fill blank per-podcast links (site, YouTube, Apple, Spotify) in show_links.yaml")
    sl.add_argument("--sources", default=str(DATA / "sources.yaml"))
    sl.add_argument("--file", default=str(DATA / "show_links.yaml"))
    sl.add_argument("--only", help="comma-separated source ids")
    sl.add_argument("--ytsearch", action="store_true", help="also search YouTube (yt-dlp) for blank channels; Mac/residential IP only")
    sl.add_argument("--websearch", action="store_true",
                    help="also look for blank Spotify pages with a free DuckDuckGo search (stops at the first rate-limit page); results are title-checked")
    sl.add_argument("--verify", action="store_true",
                    help="check set YouTube channels (>= 2 of the last 15 videos match recent feed titles) and Spotify pages; prints a table, edits nothing")
    sl.add_argument("--fix", action="store_true", help="with --verify: blank the values that are clearly wrong (mismatch, never unreachable)")
    mk = sub.add_parser("mark", help="record a stage start/end timestamp in the run's manifest.json")
    mk.add_argument("stage", choices=["fetch", "transcribe", "select", "report", "publish"])
    mk.add_argument("event", choices=["start", "end"])
    mk.add_argument("--run", required=True)
    st = sub.add_parser("stats", help="trend table across runs: stage durations, e2e and transcribed")
    st.add_argument("--runs", default=str(DATA / "runs"))
    lib = sub.add_parser("library", help="durable insight library: ingest runs, query claims and transcripts, export")
    lsub = lib.add_subparsers(dest="lib_cmd", required=True)
    ldb = argparse.ArgumentParser(add_help=False)
    ldb.add_argument("--db", help="library database (default data/library.sqlite)")
    li = lsub.add_parser("ingest", parents=[ldb], help="add runs to the library (idempotent; replaces a run's rows)")
    li.add_argument("run", nargs="*", help="run folders, e.g. runs/2026-10-23")
    li.add_argument("--all", action="store_true", help="every folder under --runs")
    li.add_argument("--runs", default=str(DATA / "runs"))
    li.add_argument("--no-transcripts", action="store_true", help="claims only; skip the transcript text index")
    lq = lsub.add_parser("query", parents=[ldb], help="find claims (or transcript passages with --transcripts)")
    lq.add_argument("--ticker")
    lq.add_argument("--person", help="speaker or episode title contains this")
    lq.add_argument("--show", help="podcast name contains this")
    lq.add_argument("--text", help="words to find; \"quote\" a phrase")
    lq.add_argument("--since", help="YYYY-MM-DD, by episode publish date")
    lq.add_argument("--until")
    lq.add_argument("--limit", type=int, default=20)
    lq.add_argument("--transcripts", action="store_true", help="search transcript text (needs --text)")
    lq.add_argument("--json", action="store_true")
    le = lsub.add_parser("export", parents=[ldb], help="all claims as JSON lines")
    le.add_argument("--since")
    le.add_argument("--until")
    le.add_argument("--out", help="file (default stdout)")
    lsub.add_parser("stats", parents=[ldb], help="what the library holds")
    p = sub.add_parser("publish", help="validate ranked.json and render the digest")
    p.add_argument("ranked")
    p.add_argument("--out")
    p.add_argument("--top-claims", type=int, default=3)
    p.add_argument("--top", type=int, help="digest only the top N ranked episodes (ranked.json keeps all)")
    stp = sub.add_parser("status", help="where is this run, and what is the single next action (daily or weekly; read-only)")
    stp.add_argument("run")
    stp.add_argument("--json", action="store_true", help="machine-readable output (schema/status.schema.json)")
    stp.add_argument("--weekly", action="store_true", help="force the weekly (rank) flow instead of auto-detecting")
    stp.add_argument("--record", action="store_true", help="also stamp select/report start/end timing the code can observe (the only write)")
    tdp = sub.add_parser("today", help="start today's daily run if it does not exist, else show its status and next action")
    tdp.add_argument("--hours", type=float, default=48)
    tdp.add_argument("--run-name", help="override the run name (default: today's local date)")
    tdp.add_argument("--runs", default=str(DATA / "runs"))
    tdp.add_argument("--json", action="store_true")
    si = sub.add_parser("site", help="build the site from the configured data root",
                        description="Reads published output from SIGMA_DATA_ROOT (default: repo/data). Research posts are selected by research/index.json, which lists slugs for research/posts/<slug>.json. Posts must match schema/research-post.schema.json and pass privacy checks; an invalid post stops the build before output is replaced.")
    si.add_argument("--out", default="dist")
    si.add_argument("--published", default=str(DATA / "published"))
    si.add_argument("--base-url", default=None, help="public origin for absolute URLs (env SIGMA_BASE_URL)")
    en = sub.add_parser("entities", help="entities.json (topics, companies, people, lenses): list what is missing, suggest companies for people")
    esub = en.add_subparsers(dest="ent_cmd", required=True)
    ecom = argparse.ArgumentParser(add_help=False)
    ecom.add_argument("--file", help="entities file (default entities.json)")
    ecom.add_argument("--published", default=str(DATA / "published"))
    esub.add_parser("check", parents=[ecom], help="new companies and people with 3+ claims, shows with no topic; exit 1 on a broken reference")
    ebf = esub.add_parser("backfill", parents=[ecom], help="suggest a company for people without one, from the role their claims gave")
    ebf.add_argument("--write", action="store_true", help="add the suggestions to entities.json")
    ca = sub.add_parser("calls", help="private ledger of each creator's stock calls and the returns since (data/calls/); fetches daily closes")
    ca.add_argument("--creator", help="one creator id from creators.json")
    ca.add_argument("--refresh", action="store_true", help="fetch prices again even when the cache is under 12 hours old")
    ca.add_argument("--published", default=str(DATA / "published"))
    so = sub.add_parser("source", help="sources.yaml: add a show from an Apple Podcasts, YouTube or feed url, or review tiers against scores")
    ssub = so.add_subparsers(dest="src_cmd", required=True)
    scom = argparse.ArgumentParser(add_help=False)
    scom.add_argument("--sources", default=str(DATA / "sources.yaml"))
    scom.add_argument("--links", default=str(DATA / "show_links.yaml"))
    scom.add_argument("--entities", default=str(DATA / "entities.json"))
    sad = ssub.add_parser("add", parents=[scom], help="add a show at tier 2 (or say it is already a source), fill its links and topics")
    sad.add_argument("url", help="Apple Podcasts show or episode url, a YouTube video or channel url, or a feed url")
    sad.add_argument("--tier", type=int, choices=[1, 2, 3], default=2, help="default 2: triage picks its best episodes; tier 1 transcribes all")
    sad.add_argument("--style", choices=STYLES, default="interview", help="influencer: a creator who picks stocks; scored apart from interviews (prompts/rank-influencer.md)")
    sad.add_argument("--topics", help="comma-separated topic ids from entities.json, e.g. ai,tech")
    sad.add_argument("--name", help="override the show name")
    sad.add_argument("--id", help="override the source id (default: slug of the name)")
    sad.add_argument("--news", action="store_true", help="daily news or market-recap show: not whispered unless transcribe --news")
    sad.add_argument("--dry-run", action="store_true")
    srv = ssub.add_parser("review", parents=[scom], help="per source: scored episodes, mean score, and whether the tier fits")
    srv.add_argument("--published", default=str(DATA / "published"))
    from . import xdaily

    xd = sub.add_parser("x", help="daily X edition: status, scan-check, prep, check, publish, prune, heartbeat, health (see skills/x-daily)")
    xsub = xd.add_subparsers(dest="x_cmd", required=True)
    xcom = argparse.ArgumentParser(add_help=False)
    xcom.add_argument("date", nargs="?", default=xdaily.today(), help="YYYY-MM-DD (default today)")
    xcom.add_argument("--published", default=str(DATA / "published"))
    xst = xsub.add_parser("status", parents=[xcom], help="where the day stands and the one next step")
    xst.add_argument("--json", action="store_true")
    xsub.add_parser("scan-check", parents=[xcom], help="validate <x dir>/scan/<date>/ against schema/x-scan.schema.json; the scanner runs it before delivering")
    xpr = xsub.add_parser("prep", parents=[xcom], help="drop noise, rank, and write days/<date>/prep.md for the editor")
    xpr.add_argument("--keep", type=int, default=xdaily.PREP_KEEP)
    xsub.add_parser("check", parents=[xcom], help="check days/<date>/edition.json: cited ids in the scan, numbers in the cited text, no copied runs")
    xsub.add_parser("publish", parents=[xcom], help="write data/published/x/editions/<date>.json (ids and Sigma's sentences only)")
    xhb = xsub.add_parser("heartbeat", help="record that a stage ran (<x dir>/heartbeat/<stage>.json); the scanner and the editor call it after every run")
    xhb.add_argument("stage", choices=xdaily.HEARTBEAT_STAGES)
    xhb.add_argument("--by", default="unknown", help="who ran it")
    xhb.add_argument("--date", default=xdaily.today(), help="the day it worked on (default today)")
    xhl = xsub.add_parser("health", help="exit 1 when the scan or the edition has gone quiet (no heartbeat or scan for --max-hours); reads only the x dir")
    xhl.add_argument("--max-hours", type=float, default=xdaily.HEARTBEAT_MAX_HOURS)
    xsub.add_parser("links", parents=[xcom], help="YouTube/Apple/Spotify links the followed accounts posted, as custom-run picks (days/<date>/links.json)")
    xpn = xsub.add_parser("prune", parents=[xcom], help="remove the posts scan <date> reports gone from X (deleted, protected) from the editions, stances and scans, and write check-ids.json for the next scan")
    xpn.add_argument("--force", action="store_true", help="act on a gone list that looks like a failed lookup (over half the checked ids)")
    sp = sub.add_parser("step", help="per-run step timing log: run a command timed, mark a step start/end, begin (lateness), table (see sigma/steplog.py)")
    sp.add_argument("--log", help="the log file (default $SIGMA_STEPLOG, else <x dir>/steps/<Pacific date>.jsonl)")
    spsub = sp.add_subparsers(dest="step_cmd", required=True)
    spr = spsub.add_parser("run", help="time a command: sigma step run NAME -- CMD...; exits with its code")
    spr.add_argument("name")
    spr.add_argument("command", nargs=argparse.REMAINDER)
    spm = spsub.add_parser("mark", help="record the start or end of a step no command wraps")
    spm.add_argument("name")
    spm.add_argument("event", choices=["start", "end"])
    spm.add_argument("--note", default="")
    spb = spsub.add_parser("begin", help="first line of a run: start time against the due time")
    spb.add_argument("--scheduled", required=True, help="HH:MM Pacific, the time the schedule says")
    spb.add_argument("--note", default="")
    spt = spsub.add_parser("table", help="the steps, the gaps between them, the slowest step")
    spt.add_argument("--json", action="store_true")
    sub.add_parser("doctor", help="check Python, audio tools, network, the configured data root and disk")
    sub.add_parser("event", add_help=False, help="append one line to the pipeline event log (data/events/); always exits 0; the line format is in sigma/events.py")
    eh = sub.add_parser("events", help="the event log: harvest each scheduled agent run's cost and time from Claude's session files")
    hsub = eh.add_subparsers(dest="events_cmd", required=True)
    hv = hsub.add_parser("harvest", help="one agent_run line per finished scheduled-task session, once each (env SIGMA_SESSIONS_DIR)")
    hv.add_argument("--dir", help="the session folder (default: this checkout's under ~/.claude/projects)")
    hv.add_argument("--min-age", type=float, default=600, help="skip a session changed in the last N seconds: still running")
    vf = sub.add_parser("verify", help="GET the live site: 200 and milliseconds to the event log; with --run, the home page and the run's page load")
    vf.add_argument("url", help="the site, e.g. https://sigma.example")
    vf.add_argument("--run", help="the run just published: home and /runs/<run>/ must load, and where that address redirects must exist")
    vf.add_argument("--signals", metavar="DATE", help="the Signals index of DATE must be served at /signals/DATE.json, valid, and listed in /signals/index.json")
    vf.add_argument("--expect", action="append", default=[], help="text the page (with --run, the page that shows the run) must contain; repeatable")
    for sp in (t, d):
        sp.add_argument("--backend", choices=BACKEND_CHOICES, help="whisper backend (env SIGMA_WHISPER_BACKEND; default auto)")
    args = ap.parse_args(argv)
    if wt := other_worktree(Path.cwd()):
        events.discard()  # a refused command did not run: it leaves no line in the real log
        sys.exit(f"sigma: this command runs the code in {ROOT}, but you are in its worktree {wt}, so it would test the wrong "
                 f"code and write the real runs/ and data/. From the worktree run "
                 f"`{sys.executable} -m sigma.cli {args.cmd} ...` instead.")
    events.command(args)
    if getattr(args, "backend", None):
        os.environ["SIGMA_WHISPER_BACKEND"] = args.backend  # the queued transcribe child inherits it
    own ={"status": status_cmd, "find": find_cmd, "custom-run": custom_run_cmd, "today": today_cmd, "doctor": doctor_cmd,
           "entities": entities_cmd,
           "calls": calls_cmd,
           "source": source_cmd,
           "x": x_cmd,
           "step": step_cmd,
           "events": events.events_cmd,
           "verify": verify.verify_cmd}
    if args.cmd == "signals-index":
        from . import signals_index

        return signals_index.signals_index_cmd(args)
    if args.cmd == "search-index":
        from . import searchindex

        return searchindex.search_index_cmd(args)
    if args.cmd in own:
        return own[args.cmd](args)
    if args.cmd == "site":
        from . import site

        return site.main(["--out", args.out, "--published", args.published] + (["--base-url", args.base_url] if args.base_url else []))
    {"fetch": fetch, "daily": daily, "transcribe": transcribe_run, "publish": publish, "check": check,
     "report": render_report, "links": links, "show-links": show_links, "rank-prep": rank_prep, "rank-merge": rank_merge, "stance-prep": stance_cmd, "stance-merge": stance_cmd, "tickers-refresh": tickers_refresh_cmd, "score-eval": score_eval_cmd, "themes-check": themes_check, "transcript-links": transcript_links_cmd, "export-published": export_published, "dedupe-published": dedupe_published, "check-claims": check_claims, "mark": mark, "stats": stats, "library": library_cmd}[args.cmd](args)


if __name__ == "__main__":
    main()
