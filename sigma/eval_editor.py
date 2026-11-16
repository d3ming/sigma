from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import shutil
import subprocess
import tomllib
from pathlib import Path
from time import monotonic

from sigma import edit, entities


def save(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate validated, blinded editor drafts on one frozen source.")
    parser.add_argument("run", type=Path)
    parser.add_argument("episode")
    parser.add_argument("output", type=Path, help="new private scratch directory")
    parser.add_argument("--variant", action="append", required=True, metavar="MODEL:EFFORT")
    parser.add_argument("--repeat", type=int, default=2)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--prompt", type=Path, help="candidate edit.md to freeze for all variants")
    args = parser.parse_args()
    variants = [variant.partition(":") for variant in args.variant]
    if args.repeat < 1 or len(set(variants)) < 2 or any(not model or not effort for model, _, effort in variants):
        parser.error("supply at least two distinct MODEL:EFFORT variants and a positive repeat count")
    if len(set(variants)) != len(variants):
        parser.error("repeat trials with --repeat")
    run = args.run.resolve()
    output = args.output.resolve()
    if any(output.is_relative_to(root) for root in (run, edit.ROOT, entities.ENTITIES_FILE.resolve().parent)):
        parser.error("keep evaluation output outside the run and source checkout")
    manifest = json.loads((run / "manifest.json").read_text())
    row = next((row for row in manifest["episodes"] if row["episode_id"] == args.episode), None)
    if row is None or not row.get("file"):
        parser.error("episode has no transcript in this run")
    source = run / row["file"]
    if not source.resolve().is_relative_to(run) or not source.is_file() or not shutil.which("codex"):
        parser.error("a local transcript and the Codex CLI are required")
    output.mkdir(mode=0o700)
    frozen = output / "frozen"
    hashes = {}
    for relative in ("prompts/edit.md", "prompts/edit-episode.md", "prompts/evaluate-edit.md",
                     "schema/editor.schema.json", ".codex/agents/podcast-editor.toml"):
        target = frozen / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        source_file = args.prompt if relative == "prompts/edit.md" and args.prompt else edit.ROOT / relative
        shutil.copyfile(source_file, target)
        hashes[relative] = sha256(target)
    shutil.copyfile(entities.ENTITIES_FILE, frozen / "entities.json")
    snapshot = frozen / "source.md"
    shutil.copyfile(source, snapshot)
    manifest_copy = frozen / "manifest.json"
    save(manifest_copy, {**manifest, "episodes": [{**row, "file": snapshot.name}]})
    role = tomllib.loads((frozen / ".codex/agents/podcast-editor.toml").read_text())["developer_instructions"]
    prompt = role + "\n\n" + (frozen / "prompts/edit-episode.md").read_text().format(
        repo=frozen, transcript=snapshot, draft="draft.json", episode_id=args.episode,
        entities=frozen / "entities.json", error=""
    )
    (output / "request.txt").write_text(prompt)
    runtime = subprocess.run(["codex", "--version"], capture_output=True, text=True, check=True).stdout.strip()
    revision = subprocess.run(["git", "-C", str(edit.ROOT), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    save(output / "protocol.json", {
        "runtime": runtime, "source_revision": revision,
        "episode": args.episode, "variants": args.variant, "repeat": args.repeat, "seed": args.seed,
        "sha256": {**hashes, **{path.name: sha256(path) for path in
                               (snapshot, manifest_copy, frozen / "entities.json", output / "request.txt")}},
    })
    trials = output / "trials"
    trials.mkdir()
    order = variants * args.repeat
    rng = random.Random(args.seed)
    rng.shuffle(order)
    validation_inputs = {
        edit.ROOT / "schema/editor.schema.json": hashes["schema/editor.schema.json"],
        entities.ENTITIES_FILE: sha256(frozen / "entities.json"),
        snapshot: sha256(snapshot),
        manifest_copy: sha256(manifest_copy),
    }
    valid = []
    for number, (model, _, effort) in enumerate(order, 1):
        workdir = trials / str(number)
        workdir.mkdir()
        started = monotonic()
        log = workdir / "run.log"
        error = edit.codex(prompt, workdir, log, settings=(model, effort))
        draft = workdir / "draft.json"
        entry = None
        if not error:
            if any(sha256(path) != expected for path, expected in validation_inputs.items()):
                parser.exit(1, "Evaluation inputs changed. Discard this comparison.\n")
            entry, error, _ = edit.check_draft(frozen, draft, args.episode, snapshot)
            if any(sha256(path) != expected for path, expected in validation_inputs.items()):
                parser.exit(1, "Evaluation inputs changed. Discard this comparison.\n")
        usage = re.findall(r"(?m)^tokens used\n([0-9,]+)$", log.read_text(errors="replace"))
        save(workdir / "result.json", {
            "cli_reported_tokens": int(usage[-1].replace(",", "")) if usage else None,
            "model": model, "effort": effort, "seconds": round(monotonic() - started, 2),
            "valid": entry is not None, "error": error,
            "sha256": sha256(draft) if draft.is_file() else None,
        })
        print(f"Trial {number} ({model}, {effort}): {error or 'valid'}", flush=True)
        if entry is not None:
            valid.append((number, entry))
    blind = output / "blind"
    blind.mkdir()
    rng.shuffle(valid)
    labels = {}
    for label, (number, entry) in enumerate(valid, 1):
        labels[str(label)] = number
        anonymous = {key: value for key, value in entry.items() if key != "prompt_version"}
        review_draft = blind / f"{label}.json"
        save(review_draft, anonymous)
        save(blind / f"{label}.validation.json", {
            "label": label, "validator": "sigma.edit.check_draft", "valid": True,
            "review_draft_sha256": sha256(review_draft),
        })
    save(output / "blind-map.json", labels)
    return int(len(valid) != len(order))


if __name__ == "__main__":
    raise SystemExit(main())
