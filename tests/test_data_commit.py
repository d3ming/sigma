import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "deploy" / "mac" / "data-commit.sh"
CODE = Path(__file__).parent.parent
pytestmark = [pytest.mark.slow, pytest.mark.skipif(shutil.which("zsh") is None, reason="data-commit.sh is a zsh script")]


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def common_dir(repo):
    value = Path(git("rev-parse", "--git-common-dir", cwd=repo))
    return (value if value.is_absolute() else repo / value).resolve()


def working_files(root):
    return {str(path.relative_to(root)): path.read_bytes() if not path.is_symlink() else os.readlink(path).encode()
            for path in root.rglob("*") if path.is_file() and ".git" not in path.relative_to(root).parts}


def private_source(tmp_path):
    origin, source = tmp_path / "private.git", tmp_path / "operator"
    subprocess.run(["git", "init", "--bare", "-q", "--initial-branch=main", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(source)], check=True, capture_output=True)
    git("config", "user.name", "Fixture", cwd=source)
    git("config", "user.email", "fixture@example.invalid", cwd=source)
    data = source / "sigma"
    data.mkdir()
    (data / "site.json").write_text('{"version":1}\n')
    (data / ".gitignore").write_text("*.sqlite\nruns/\n.env*\n.private-words\n")
    (data / "runs").mkdir()
    (data / "runs" / "baseline-transcript.md").write_text("old local transcript\n")
    (data / "runs" / "episode-01.md").write_text("old local episode transcript\n")
    (data / "runs" / "feed-cache.json").write_text("old local feed cache\n")
    (data / "library.sqlite").write_bytes(b"old local sqlite")
    (data / ".env.local").write_text("token=old-local\n")
    (data / ".private-words").write_text("old local private marker\n")
    (source / "AGENTS.md").write_text("Fixture private repo\n")
    git("add", "sigma/site.json", "sigma/.gitignore", "AGENTS.md", cwd=source)
    subprocess.run(["git", "add", "-f", "sigma/runs/baseline-transcript.md", "sigma/runs/feed-cache.json",
                    "sigma/runs/episode-01.md",
                    "sigma/library.sqlite", "sigma/.env.local", "sigma/.private-words"], cwd=source, check=True)
    git("commit", "-qm", "fixture baseline", cwd=source)
    git("push", "-q", "-u", "origin", "main", cwd=source)
    git("switch", "-q", "-c", "sigma-ingest", cwd=source)
    return origin, source, data, CODE


def invoke(source, data, code, *args):
    return subprocess.run(["zsh", str(code / "deploy/mac/data-commit.sh"), *args], cwd=source,
                          env={**os.environ, "SIGMA_DATA_ROOT": str(data)}, capture_output=True, text=True)


def test_branch_delta_lands_on_private_main_without_touching_checkout_or_siblings(tmp_path):
    origin, source, data, code = private_source(tmp_path)
    (data / "site.json").write_text('{"version":2}\n')
    git("add", "sigma/site.json", cwd=source)
    (data / "runs" / "baseline-transcript.md").write_text("changed transcript stays local\n")
    (data / "runs" / "episode-01.md").write_text("changed generic transcript stays local\n")
    (data / "runs" / "feed-cache.json").write_text("changed feed cache stays local\n")
    (data / "library.sqlite").write_bytes(b"changed sqlite")
    (data / ".env.local").write_text("token=changed-local\n")
    (data / ".private-words").write_text("changed local private marker\n")
    git("commit", "-qm", "change owned site config", cwd=source)
    (data / "published").mkdir()
    (data / "published" / "signals.json").write_text('{"signals":1}\n')
    (data / "runs" / "ignored-transcript.md").write_text("untracked raw transcript stays local\n")
    sibling = source / "research" / "dirty.txt"
    sibling.parent.mkdir()
    sibling.write_text("leave another writer alone\n")
    head_before = git("rev-parse", "HEAD", cwd=source)
    status_before = git("status", "--porcelain", cwd=source)
    files_before = working_files(source)

    remote_main_before = git("rev-parse", "refs/heads/main", cwd=origin)
    plan = invoke(source, data, code, "--plan")
    assert plan.returncode == 0, plan.stderr
    planned_main = next(line.split(": ", 1)[1] for line in plan.stdout.splitlines() if line.startswith("[data] main: "))
    planned_tree = next(line.split(": ", 1)[1] for line in plan.stdout.splitlines() if line.startswith("[data] owned tree: "))
    assert planned_main == remote_main_before
    assert git("rev-parse", "refs/heads/main", cwd=origin) == remote_main_before
    assert git("status", "--porcelain", cwd=source) == status_before
    assert working_files(source) == files_before
    assert git("branch", "--list", "sigma-data-*", cwd=source) == ""

    refused = invoke(source, data, code, "--expect-tree", "0" * 40, "land the current edition")
    assert refused.returncode == 1
    assert "does not match the approved tree" in refused.stderr
    assert git("rev-parse", "refs/heads/main", cwd=origin) == remote_main_before
    assert git("status", "--porcelain", cwd=source) == status_before
    assert working_files(source) == files_before

    result = invoke(source, data, code, "--expect-tree", planned_tree, "land the current edition")

    assert result.returncode == 0, result.stderr
    main = git("rev-parse", "refs/remotes/origin/main", cwd=source)
    assert f"[data] main: {main}" in result.stdout
    assert f"[data] owned tree: {planned_tree}" in result.stdout
    assert f"[data] owned tree: {git('rev-parse', f'{main}:sigma', cwd=source)}" in result.stdout
    assert git("show", f"{main}:sigma/site.json", cwd=source) == '{"version":2}'
    assert git("show", f"{main}:sigma/published/signals.json", cwd=source) == '{"signals":1}'
    assert git("show", f"{main}:sigma/runs/baseline-transcript.md", cwd=source) == "old local transcript"
    assert git("show", f"{main}:sigma/runs/episode-01.md", cwd=source) == "old local episode transcript"
    assert git("show", f"{main}:sigma/runs/feed-cache.json", cwd=source) == "old local feed cache"
    assert git("show", f"{main}:sigma/library.sqlite", cwd=source) == "old local sqlite"
    assert git("show", f"{main}:sigma/.env.local", cwd=source) == "token=old-local"
    assert git("show", f"{main}:sigma/.private-words", cwd=source) == "old local private marker"
    assert git("rev-parse", "HEAD", cwd=source) == head_before
    assert git("status", "--porcelain", cwd=source) == status_before
    assert working_files(source) == files_before
    assert git("branch", "--show-current", cwd=source) == "sigma-ingest"
    assert git("branch", "--list", "sigma-data-*", cwd=source) == ""


def test_conflict_with_new_private_main_stops_without_changing_source(tmp_path):
    origin, source, data, code = private_source(tmp_path)
    (data / "site.json").write_text('{"version":"ingest"}\n')
    git("add", "sigma/site.json", cwd=source)
    git("commit", "-qm", "ingest site config", cwd=source)
    sibling = source / "research" / "keep.txt"
    sibling.parent.mkdir()
    sibling.write_text("unrelated dirty file\n")
    other = tmp_path / "concurrent-main"
    subprocess.run(["git", "clone", "-q", str(origin), str(other)], check=True, capture_output=True)
    git("config", "user.name", "Fixture", cwd=other)
    git("config", "user.email", "fixture@example.invalid", cwd=other)
    (other / "sigma" / "site.json").write_text('{"version":"main"}\n')
    git("add", "sigma/site.json", cwd=other)
    git("commit", "-qm", "concurrent main change", cwd=other)
    git("push", "-q", "origin", "main", cwd=other)
    head_before = git("rev-parse", "HEAD", cwd=source)
    status_before = git("status", "--porcelain", cwd=source)
    files_before = working_files(source)
    result = invoke(source, data, code, "conflicting landing")
    assert result.returncode == 1
    assert "conflicts with private main" in result.stderr
    assert git("rev-parse", "HEAD", cwd=source) == head_before
    assert git("status", "--porcelain", cwd=source) == status_before
    assert working_files(source) == files_before
    main = git("rev-parse", "refs/heads/main", cwd=origin)
    assert git("show", f"{main}:sigma/site.json", cwd=source) == '{"version":"main"}'
    assert sibling.read_text() == "unrelated dirty file\n"
    assert git("branch", "--list", "sigma-data-*", cwd=source) == ""


def test_data_commit_refuses_preexisting_staged_files_without_touching_them(tmp_path):
    _, source, data, code = private_source(tmp_path)
    staged = source / "research" / "staged.json"
    staged.parent.mkdir()
    staged.write_text("keep staged\n")
    git("add", "research/staged.json", cwd=source)
    before = git("diff", "--cached", "--binary", cwd=source)
    result = invoke(source, data, code)
    assert result.returncode == 1
    assert "pre-existing staged files" in result.stderr
    assert git("diff", "--cached", "--binary", cwd=source) == before
    assert git("rev-parse", "HEAD", cwd=source) == git("rev-parse", "refs/remotes/origin/main", cwd=source)
    git("reset", "-q", "HEAD", "--", "research/staged.json", cwd=source)
    (data / "site.json").unlink()
    deleted = invoke(source, data, code)
    assert deleted.returncode == 1
    assert "delete private data without a saved copy" in deleted.stderr
    assert git("rev-parse", "HEAD", cwd=source) == git("rev-parse", "refs/remotes/origin/main", cwd=source)
    assert git("show", "refs/remotes/origin/main:sigma/site.json", cwd=source) == '{"version":1}'


def test_data_commit_refuses_data_inside_the_public_sigma_checkout(tmp_path):
    public = tmp_path / "sigma"
    public.mkdir()
    git("init", "-q", "--initial-branch=main", cwd=public)
    git("config", "user.name", "Fixture", cwd=public)
    git("config", "user.email", "fixture@example.invalid", cwd=public)
    script = public / "deploy/mac/data-commit.sh"
    script.parent.mkdir(parents=True)
    shutil.copy(SCRIPT, script)
    git("add", "deploy/mac/data-commit.sh", cwd=public)
    git("commit", "-qm", "fixture", cwd=public)
    data = public / "data"
    data.mkdir()
    before = git("rev-parse", "HEAD", cwd=public)
    result = invoke(public, data, public)
    assert result.returncode == 1
    assert "public Sigma repository" in result.stderr
    assert git("rev-parse", "HEAD", cwd=public) == before
    assert git("diff", "--cached", cwd=public) == ""


def test_data_commit_refuses_private_path_in_linked_public_worktree(tmp_path):
    origin, public, linked = tmp_path / "origin.git", tmp_path / "public", tmp_path / "linked"
    subprocess.run(["git", "init", "--bare", "-q", "--initial-branch=main", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(public)], check=True, capture_output=True)
    git("config", "user.name", "Fixture", cwd=public)
    git("config", "user.email", "fixture@example.invalid", cwd=public)
    script = public / "deploy/mac/data-commit.sh"
    script.parent.mkdir(parents=True)
    shutil.copy(SCRIPT, script)
    git("add", "deploy/mac/data-commit.sh", cwd=public)
    git("commit", "-qm", "fixture", cwd=public)
    git("push", "-q", "-u", "origin", "main", cwd=public)
    public_data = public / "private-data"
    public_data.mkdir()
    refused = invoke(public, public_data, public, "must refuse public repository data")
    assert refused.returncode == 1
    assert "public Sigma repository" in refused.stderr
    git("worktree", "add", "-q", "-b", "linked-data", str(linked), "main", cwd=public)
    git("branch", "--set-upstream-to=origin/main", "linked-data", cwd=public)
    data = linked / "private-data"
    data.mkdir()
    (data / "site.json").write_text('{"site_name":"Sigma"}')
    assert common_dir(public) == common_dir(linked)
    before = git("rev-parse", "origin/main", cwd=public)
    result = invoke(public, data, public, "must refuse linked checkout data")
    assert result.returncode == 1
    assert "linked checkout of the public Sigma repository" in result.stderr
    assert subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=linked).returncode == 0
    assert git("rev-parse", "origin/main", cwd=public) == before
    assert git("rev-parse", "HEAD", cwd=linked) == before
