from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import jsonschema

from . import editor, entities, ranked

try:
    import tomllib
except ImportError:
    import tomli as tomllib

ROOT = Path(__file__).resolve().parent.parent
AGENT = ROOT / ".codex" / "agents" / "podcast-editor.toml"
DRAFTS = "edits"
ATTEMPT_SECONDS = 3600


def agent() -> tuple[str, str, str]:
    cfg = tomllib.loads(AGENT.read_text())
    return cfg["model"], cfg["model_reasoning_effort"], cfg["developer_instructions"]


def codex(prompt: str, workdir: Path, log: Path) -> str | None:
    """One `codex exec` with the podcast_editor role's model and effort. None when it ran, else why not."""
    model, effort, _ = agent()
    cmd = ["codex", "exec", "-m", model, "-c", f"model_reasoning_effort={effort}", "-s", "workspace-write",
           "-C", str(workdir), "--skip-git-repo-check", "--ephemeral"]
    try:
        with log.open("a") as out:
            done = subprocess.run(cmd, input=prompt, text=True, stdout=out, stderr=subprocess.STDOUT, timeout=ATTEMPT_SECONDS)
    except subprocess.TimeoutExpired:
        return f"codex ran past {ATTEMPT_SECONDS} s"
    return None if done.returncode == 0 else f"codex exited {done.returncode}"


def check_draft(run: Path, draft: Path, episode_id: str) -> tuple[dict | None, str]:
    """(entry, "") when the draft is for this episode and passes the editor check against that episode's transcript, else (None, why)."""
    try:
        entry = json.loads(draft.read_text())
        if not isinstance(entry, dict) or entry.get("episode_id") != episode_id:
            found = entry.get("episode_id") if isinstance(entry, dict) else None
            return None, f"the draft is for episode {found!r}, not {episode_id!r}"
        editor.validate(run, {"version": 1, "episodes": [entry]})
    except FileNotFoundError:
        return None, "no draft was written"
    except jsonschema.ValidationError as exc:
        return None, f"{exc.message} at {'/'.join(map(str, exc.absolute_path))}"
    except (OSError, ValueError) as exc:
        return None, str(exc)
    return entry, ""


def edit_one(run: Path, row: dict, source: Path, fixes: int) -> tuple[dict | None, str, int]:
    """An existing draft that passes is used as it stands (a hand repair); one that fails goes back to Codex with the check's
    error, up to `fixes` rewrites after the first run. Returns (entry or None, last error, Codex runs used)."""
    drafts = run / DRAFTS
    safe = row["episode_id"].replace(":", "_")
    draft, log = drafts / f"{safe}.json", drafts / f"{safe}.log"
    _, _, role = agent()
    facts = {"repo": ROOT, "transcript": source, "draft": draft, "episode_id": row["episode_id"], "entities": entities.ENTITIES_FILE}
    entry, error = check_draft(run, draft, row["episode_id"])
    runs = 0
    while entry is None and runs <= fixes:
        runs += 1
        template = "edit-fix.md" if draft.exists() else "edit-episode.md"
        prompt = ((role + "\n\n") if template == "edit-episode.md" else "") + (ROOT / "prompts" / template).read_text().format(**facts, error=error)
        if failure := codex(prompt, drafts, log):
            return None, failure, runs
        entry, error = check_draft(run, draft, row["episode_id"])
    return entry, "" if entry else error, runs


def merge(run: Path, entry: dict) -> None:
    path = run / editor.FILE
    data = json.loads(path.read_text()) if path.exists() else {"version": 1, "episodes": []}
    data.setdefault("prompt_version", editor.PROMPT_VERSION)
    data["episodes"] = [e for e in data["episodes"] if e["episode_id"] != entry["episode_id"]] + [entry]
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    os.replace(tmp, path)


def edit_cmd(args) -> None:
    run = Path(args.run).resolve()
    if not shutil.which("codex"):
        sys.exit("[edit] codex is not installed")
    try:
        data = ranked.load(run / "ranked.json")
        args.min_score = args.min_score or editor.MIN_SCORE
        todo = editor.unedited(run, data, args.min_score)
    except (OSError, ValueError, ranked.RankedError) as exc:
        sys.exit(f"[edit] {exc}")
    todo = todo[:args.limit] if args.limit else todo
    if not todo:
        print(f"[edit] every transcribed ranked episode scoring {args.min_score}+ has an editor.json entry")
        return
    model, effort, _ = agent()
    print(f"[edit] {len(todo)} episode(s) scoring {args.min_score}+ to write with {model} ({effort}), {args.jobs} at a time")
    manifest = {r["episode_id"]: r for r in json.loads((run / "manifest.json").read_text())["episodes"]}
    (run / DRAFTS).mkdir(exist_ok=True)
    failed = []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        jobs = {pool.submit(edit_one, run, row, run / manifest[row["episode_id"]]["file"], args.fixes): row for row in todo}
        for job in as_completed(jobs):
            eid = jobs[job]["episode_id"]
            entry, error, attempts = job.result()
            if entry is None:
                failed.append(eid)
                print(f"[edit] {eid} failed after {attempts} Codex run(s): {error} (draft and log in {run / DRAFTS})")
                continue
            merge(run, entry)
            print(f"[edit] {eid} checked and merged ({f'{attempts} Codex run(s)' if attempts else 'existing draft, no Codex run'})")
    try:
        checked = editor.load(run)
    except (OSError, ValueError, jsonschema.ValidationError) as exc:
        sys.exit(f"[edit] editor.json fails its check: {exc}")
    print(f"[editor] {len(checked)} episodes in {editor.FILE}")
    if failed:
        sys.exit(f"[edit] {len(failed)} episode(s) have no entry: {', '.join(failed)}")
