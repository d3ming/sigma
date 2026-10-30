#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PY=${SIGMA_PYTHON:-}
if [ -z "$PY" ]; then
  COMMON_DIR=$(git -C "$ROOT" rev-parse --git-common-dir)
  case "$COMMON_DIR" in /*) ;; *) COMMON_DIR="$ROOT/$COMMON_DIR" ;; esac
  MAIN_CHECKOUT=$(CDPATH= cd -- "$COMMON_DIR/.." && pwd)
  if [ -x "$ROOT/.venv/bin/python" ]; then PY="$ROOT/.venv/bin/python"; elif [ -x "$MAIN_CHECKOUT/.venv/bin/python" ]; then PY="$MAIN_CHECKOUT/.venv/bin/python"; else PY=python3; fi
fi
exec "$PY" - "$ROOT" "$@" <<'PY'
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
from datetime import datetime, timezone

root = pathlib.Path(sys.argv[1])
args = sys.argv[2:]
state = root / ".vercel"
plans = pathlib.Path(os.environ.get("SIGMA_RELEASE_PLAN_DIR", state / "release-plans"))
deploy = root / "deploy" / "mac" / "site-deploy.sh"


def refuse(message):
    raise SystemExit(f"[publish] refused: {message}")


def git(*items, check=True):
    result = subprocess.run(["git", *items], cwd=root, text=True, capture_output=True)
    if check and result.returncode:
        refuse(result.stderr.strip() or f"git {' '.join(items)} failed")
    return result


def digest_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def publication_hash(path):
    digest = hashlib.sha256()
    for item in sorted(p for p in path.rglob("*") if p.is_file()):
        name = item.relative_to(path).as_posix().encode()
        payload = item.read_bytes()
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def publication_manifest(path, source_sha, artifact_hash):
    files = []
    for item in sorted(p for p in path.rglob("*") if p.is_file()):
        files.append({"path": item.relative_to(path).as_posix(), "sha256": digest_file(item)})
    return {"source_sha": source_sha, "publication_hash": artifact_hash, "files": files}


def private_data_state(*args):
    helper = root / "deploy" / "mac" / "data-commit.sh"
    try:
        result = subprocess.run([str(helper), *args], cwd=root, text=True, capture_output=True)
    except OSError as exc:
        refuse(f"private data helper could not run: {exc}")
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    if result.returncode:
        refuse("private data landing failed; version tag and deployment were not attempted")
    main = re.search(r"(?m)^\[data\] main: ([0-9a-f]{40}|[0-9a-f]{64})$", result.stdout)
    tree = re.search(r"(?m)^\[data\] owned tree: ([0-9a-f]{40}|[0-9a-f]{64})$", result.stdout)
    if not main or not tree:
        refuse("private data helper did not report its main commit and owned tree")
    return {"main": main.group(1), "tree": tree.group(1)}


def tag_remote(tag):
    refs = git("ls-remote", "origin", f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}", check=False)
    if refs.returncode not in (0, 2):
        refuse(refs.stderr.strip() or "could not inspect the remote version tag")
    rows = {}
    for line in refs.stdout.splitlines():
        fields = line.split()
        if len(fields) == 2:
            rows[fields[1]] = fields[0]
    raw = rows.get(f"refs/tags/{tag}")
    peeled = rows.get(f"refs/tags/{tag}^{{}}")
    if raw is None:
        return None
    if peeled is None:
        refuse(f"remote tag {tag} is not annotated")
    return {"object": raw, "commit": peeled}


def validate_tag_object(object_id, tag, email, commit):
    fields = {}
    for line in git("cat-file", "-p", object_id).stdout.splitlines():
        if not line:
            break
        key, _, value = line.partition(" ")
        fields[key] = value
    tagger = fields.get("tagger", "")
    if fields.get("type") != "commit" or fields.get("object") != commit or fields.get("tag") != tag:
        refuse(f"version tag {tag} does not directly identify reviewed main")
    if not re.fullmatch(rf"Sigma <{re.escape(email)}> [0-9]+ [+-][0-9]{{4}}", tagger):
        refuse(f"version tag {tag} does not use the prepared Sigma no-reply identity")


def verify_remote_tag(tag, email, commit):
    remote = tag_remote(tag)
    if remote is None or remote["commit"] != commit:
        refuse(f"remote version tag {tag} does not point to reviewed main")
    git("fetch", "-q", "--no-tags", "origin", f"refs/tags/{tag}")
    fetched = git("rev-parse", "FETCH_HEAD").stdout.strip()
    if fetched != remote["object"]:
        refuse(f"remote version tag {tag} changed during verification")
    validate_tag_object(fetched, tag, email, commit)
    return remote


def version_tag():
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'(?m)^version\s*=\s*["\']([^"\']+)["\']\s*$', text)
    if not match:
        refuse("could not read the package version from pyproject.toml")
    version = match.group(1)
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        refuse(f"unsupported package version {version!r}")
    return f"v{version}"


def tagger_email():
    result = git("config", "--local", "user.email", check=False)
    email = result.stdout.strip()
    if result.returncode or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@users\.noreply\.github\.com", email, re.IGNORECASE):
        refuse("local Git identity must use a GitHub no-reply email before preparing a version tag")
    return email


def checked_main():
    branch = git("branch", "--show-current").stdout.strip()
    if branch != "main":
        refuse(f"publish only runs from main, not {branch or 'detached HEAD'}")
    git("fetch", "-q", "origin", "main")
    head = git("rev-parse", "HEAD").stdout.strip()
    upstream = git("rev-parse", "origin/main").stdout.strip()
    if head != upstream:
        refuse("checked-out main must exactly match origin/main")
    if git("status", "--porcelain", "--untracked-files=all").stdout:
        refuse("main checkout has tracked, staged, or untracked changes")
    return head


def linked_project():
    path = root / ".vercel" / "project.json"
    if not path.is_file():
        refuse("this checkout is not linked to its production Vercel project")
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
        project_id = config["projectId"]
        team_id = config["orgId"]
    except (ValueError, KeyError, TypeError):
        refuse("the linked Vercel project identity is incomplete")
    if not isinstance(project_id, str) or not isinstance(team_id, str):
        refuse("the linked Vercel project identity is invalid")
    return path, project_id, team_id


def check_tag_for_prepare(tag, head, email):
    remote = tag_remote(tag)
    if remote is not None and remote["commit"] != head:
        refuse(f"version tag {tag} already points to {remote['commit'][:12]}, not current main {head[:12]}; bump pyproject.toml")
    if remote is not None:
        verify_remote_tag(tag, email, head)
    return remote


def previous_version(tag, head):
    result = git("ls-remote", "--tags", "origin", "refs/tags/v*", check=False)
    if result.returncode:
        refuse(result.stderr.strip() or "could not inspect previous remote version tags")
    records = {}
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) == 2:
            records[fields[1]] = fields[0]
    current = tuple(int(part) for part in tag[1:].split("."))
    candidates = []
    for ref, commit in records.items():
        if not ref.endswith("^{}"):
            continue
        name = ref[:-3]
        match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", name)
        if not match or name == tag:
            continue
        version = tuple(int(part) for part in match.groups())
        if version >= current:
            continue
        if git("cat-file", "-e", f"{commit}^{{commit}}", check=False).returncode:
            continue
        if git("merge-base", "--is-ancestor", commit, head, check=False).returncode:
            continue
        candidates.append((version, name, commit))
    return max(candidates, default=(None, None, None))[1:]


def prepare():
    head = checked_main()
    email = tagger_email()
    tag = version_tag()
    existing = check_tag_for_prepare(tag, head, email)
    project_path, project_id, team_id = linked_project()
    data_before = private_data_state("--plan")
    print("[publish] building and checking the frozen production publication")
    result = subprocess.run([str(deploy), "--preflight", head], cwd=root, text=True, capture_output=True)
    output = result.stdout + result.stderr
    sys.stdout.write(output)
    if result.returncode:
        refuse("production publication preflight failed")
    match = re.search(r"(?m)^\[site\] production build content: ([0-9a-f]{64})$", output)
    if not match:
        refuse("preflight did not return a full publication hash")
    artifact_hash = match.group(1)
    artifact = state / "publication" / artifact_hash / ".vercel" / "output"
    if not artifact.is_dir() or publication_hash(artifact) != artifact_hash:
        refuse("frozen publication is missing or changed")
    data_after = private_data_state("--plan")
    if data_before["tree"] != data_after["tree"]:
        refuse("private data changed during the production build; prepare a new publication")
    manifest = publication_manifest(artifact, head, artifact_hash)
    manifest_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    manifest_hash = hashlib.sha256(manifest_text.encode()).hexdigest()
    project_hash = digest_file(project_path)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    previous_tag, previous_sha = previous_version(tag, head)
    if existing is not None:
        changes = "This plan refreshes published data for the already tagged source commit."
    else:
        if previous_sha is None:
            previous_sha = git("rev-list", "--max-parents=0", head).stdout.splitlines()[0]
        changes = git("log", "--first-parent", "--format=- %h %s", f"{previous_sha}..{head}").stdout.strip()
        if not changes:
            changes = "No source commits since the previous version tag; this publication carries updated data."
    notes = (
        f"# {tag}\n\n"
        f"Production publication prepared from reviewed `main` at `{head}`.\n\n"
        f"{changes}\n\n"
        f"Frozen publication content: `{artifact_hash}`.\n"
    )
    payload = {
        "schema": 2,
        "source_sha": head,
        "tag": tag,
        "artifact_hash": artifact_hash,
        "data_main": data_after["main"],
        "data_tree": data_after["tree"],
        "manifest_sha256": manifest_hash,
        "project_hash": project_hash,
        "project_id": project_id,
        "team_id": team_id,
        "target": "production",
        "notes_sha256": hashlib.sha256(notes.encode()).hexdigest(),
        "tagger_email_sha256": hashlib.sha256(email.encode()).hexdigest(),
        "prepared_at": now,
        "existing_tag": existing is not None,
    }
    plan_id = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    plans.mkdir(parents=True, exist_ok=True)
    plan_path = plans / f"{plan_id}.json"
    notes_path = plans / f"{plan_id}.md"
    manifest_path = plans / f"{plan_id}.manifest.json"
    plan_path.write_text(json.dumps({**payload, "plan_id": plan_id}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    notes_path.write_text(notes, encoding="utf-8")
    manifest_path.write_text(manifest_text, encoding="utf-8")
    print(f"[publish] prepared {tag} from {head[:12]}")
    print(f"[publish] plan: {plan_id}")
    print(f"[publish] saved: {plan_path}")
    print(f"[publish] notes: {notes_path}")
    print(f"[publish] manifest: {manifest_path}")
    return plan_id


def load_plan(plan_id):
    if not re.fullmatch(r"[0-9a-f]{64}", plan_id):
        refuse("APPROVE must be the full 64-character plan identifier")
    plan_path = plans / f"{plan_id}.json"
    notes_path = plans / f"{plan_id}.md"
    manifest_path = plans / f"{plan_id}.manifest.json"
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        notes = notes_path.read_text(encoding="utf-8")
        manifest_text = manifest_path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        refuse(f"plan {plan_id} or its release notes are missing")
    if plan.get("schema") != 2 or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", str(plan.get("data_tree", ""))):
        refuse("saved plan predates private data synchronization; prepare a new plan")
    payload = {key: value for key, value in plan.items() if key != "plan_id"}
    expected = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if plan.get("plan_id") != plan_id or expected != plan_id:
        refuse("saved plan no longer matches its identifier")
    if hashlib.sha256(notes.encode()).hexdigest() != plan.get("notes_sha256"):
        refuse("saved release notes changed after preparation")
    if hashlib.sha256(manifest_text.encode()).hexdigest() != plan.get("manifest_sha256"):
        refuse("saved publication manifest changed after preparation")
    return plan


def checked_artifact(plan):
    artifact = state / "publication" / plan["artifact_hash"]
    output = artifact / ".vercel" / "output"
    project_path, project_id, team_id = linked_project()
    if digest_file(project_path) != plan["project_hash"] or project_id != plan["project_id"] or team_id != plan["team_id"]:
        refuse("linked Vercel project changed after preparation")
    if not output.is_dir() or publication_hash(output) != plan["artifact_hash"]:
        refuse("frozen publication changed after preparation")
    expected_manifest = publication_manifest(output, plan["source_sha"], plan["artifact_hash"])
    manifest_path = plans / f"{plan['plan_id']}.manifest.json"
    if json.loads(manifest_path.read_text(encoding="utf-8")) != expected_manifest:
        refuse("frozen publication does not match its saved manifest")
    staged_project = artifact / ".vercel" / "project.json"
    if not staged_project.is_file() or digest_file(staged_project) != plan["project_hash"]:
        refuse("frozen publication is linked to a different Vercel project")


def apply(plan_id):
    plan = load_plan(plan_id)
    head = checked_main()
    email = tagger_email()
    if head != plan["source_sha"]:
        refuse("main advanced or changed after preparation; prepare a new plan")
    if hashlib.sha256(email.encode()).hexdigest() != plan.get("tagger_email_sha256"):
        refuse("local Git no-reply identity changed after preparation")
    checked_artifact(plan)
    remote = tag_remote(plan["tag"])
    if remote is not None:
        if remote["commit"] != head:
            refuse(f"version tag {plan['tag']} points to a different commit")
        verify_remote_tag(plan["tag"], email, head)
    else:
        local = git("show-ref", "--verify", f"refs/tags/{plan['tag']}", check=False)
        if local.returncode == 0:
            tag_type = git("cat-file", "-t", f"refs/tags/{plan['tag']}").stdout.strip()
            tagged = git("rev-parse", f"refs/tags/{plan['tag']}^{{commit}}").stdout.strip()
            if tag_type != "tag" or tagged != head:
                refuse(f"local version tag {plan['tag']} exists with a different or lightweight target")
            validate_tag_object(git("rev-parse", f"refs/tags/{plan['tag']}").stdout.strip(), plan["tag"], email, head)
        else:
            local = None
    data = private_data_state("--expect-tree", plan["data_tree"])
    if data["tree"] != plan["data_tree"]:
        refuse("private data tree differs from the prepared publication")
    if remote is None:
        if local is None:
            notes_path = plans / f"{plan_id}.md"
            git("-c", "user.name=Sigma", "-c", f"user.email={email}", "tag", "-a", "--cleanup=verbatim", plan["tag"], "-F", str(notes_path))
        git("push", "origin", f"refs/tags/{plan['tag']}:refs/tags/{plan['tag']}")
        verify_remote_tag(plan["tag"], email, head)
    print(f"[publish] verified {plan['tag']} at {head[:12]}")
    subprocess.run([str(deploy), "--deploy-staged", plan["artifact_hash"], plan_id], cwd=root, check=True)


def help_text():
    print("usage: make publish [APPROVE=<plan-id>]")
    print("Run from clean main matching origin/main; the version tag comes from pyproject.toml.")
    print("SIGMA_DATA_ROOT supplies private inputs; each published run needs its source under runs/<run>.")
    print("By default, make publish prepares, validates, saves private data, tags, and deploys the exact frozen production build.")
    print("Use make publish PREPARE_ONLY=1 to inspect a plan without saving private data or pushing a tag/site.")
    print("Use make publish APPROVE=<full-plan-id> to apply a previously inspected plan and its exact frozen build.")


if args in (["--help"], ["-h"]):
    help_text()
elif not args:
    approval = os.environ.get("APPROVE", "")
    prepare_only = os.environ.get("PREPARE_ONLY", "")
    if prepare_only not in ("", "1"):
        refuse("PREPARE_ONLY must be 1 when set")
    if approval and prepare_only:
        refuse("APPROVE and PREPARE_ONLY cannot be used together")
    if approval:
        apply(approval)
    elif prepare_only:
        plan_id = prepare()
        print("[publish] no tag pushed and no deployment uploaded; inspect the saved plan, then apply with make publish APPROVE=" + plan_id)
    else:
        plan_id = prepare()
        print("[publish] applying the prepared plan")
        apply(plan_id)
else:
    help_text()
    raise SystemExit(2)
PY
