import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "deploy" / "mac" / "data-commit.sh"
CODE = Path(__file__).parent.parent
OWNED_CHANGES = {"site.json": '{"version":2}\n', "published/signals.json": '{"signals":1}\n'}
pytestmark = [pytest.mark.slow, pytest.mark.skipif(shutil.which("zsh") is None, reason="data-commit.sh is a zsh script")]


def git(*args, cwd):
    return subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


def common_dir(repo):
    value = Path(git("rev-parse", "--git-common-dir", cwd=repo))
    return (value if value.is_absolute() else repo / value).resolve()


def working_files(root):
    return {str(path.relative_to(root)): path.read_bytes() if not path.is_symlink() else os.readlink(path).encode()
            for path in root.rglob("*") if path.is_file() and ".git" not in path.relative_to(root).parts}


def checkout_state(source):
    """What a landing must leave alone in the operator's checkout: branches, current branch and index, working files."""
    return (git("for-each-ref", "refs/heads", cwd=source), git("status", "--porcelain", "--branch", cwd=source), working_files(source))


def owned_tree_after(origin, changes):
    """The tree sigma/ must have on private main once `changes` land, built from main's own tree with plumbing."""
    env = {**os.environ, "GIT_INDEX_FILE": str(origin.parent / "expected.index")}
    run = lambda *args, **kw: subprocess.run(["git", *args], cwd=origin, env=env, check=True, capture_output=True, text=True, **kw).stdout.strip()
    run("read-tree", "main:sigma")
    for name, text in changes.items():
        run("update-index", "--add", "--cacheinfo", f"100644,{run('hash-object', '-w', '--stdin', input=text)},{name}")
    return run("write-tree")


@pytest.fixture(scope="module")
def private_template(tmp_path_factory):
    return build_private_template(tmp_path_factory.mktemp("private-template"))


def build_private_template(root):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    origin, source = root / "private.git", root / "operator"
    run = lambda *args, cwd=root: subprocess.run(args, cwd=cwd, check=True, capture_output=True, env=env)
    run("git", "init", "--bare", "-q", "--initial-branch=main", str(origin))
    run("git", "clone", "-q", str(origin), str(source))
    run("git", "config", "user.name", "Fixture", cwd=source)
    run("git", "config", "user.email", "fixture@example.invalid", cwd=source)
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
    run("git", "add", "-f", "-A", cwd=source)
    run("git", "commit", "-qm", "fixture baseline", cwd=source)
    run("git", "push", "-q", "-u", "origin", "main", cwd=source)
    run("git", "switch", "-q", "-c", "sigma-ingest", cwd=source)
    return root


@pytest.fixture
def private_source(tmp_path, private_template):
    """The operator's checkout on branch sigma-ingest and its private origin, copied from one fixture built per module."""
    origin, source = tmp_path / "private.git", tmp_path / "operator"
    shutil.copytree(private_template / "private.git", origin, symlinks=True)
    shutil.copytree(private_template / "operator", source, symlinks=True)
    config = source / ".git" / "config"
    config.write_text(config.read_text().replace(str(private_template / "private.git"), str(origin)))
    return origin, source, source / "sigma", CODE


def invoke(source, data, code, *args):
    return subprocess.run(["zsh", str(code / "deploy/mac/data-commit.sh"), *args], cwd=source,
                          env={**os.environ, "SIGMA_DATA_ROOT": str(data)}, capture_output=True, text=True)


def edit_branch_delta(source, data):
    """A branch that committed a new site.json, with the files the landing must never take edited, untracked or beside it."""
    (data / "site.json").write_text(OWNED_CHANGES["site.json"])
    git("add", "sigma/site.json", cwd=source)
    (data / "runs" / "baseline-transcript.md").write_text("changed transcript stays local\n")
    (data / "runs" / "episode-01.md").write_text("changed generic transcript stays local\n")
    (data / "runs" / "feed-cache.json").write_text("changed feed cache stays local\n")
    (data / "library.sqlite").write_bytes(b"changed sqlite")
    (data / ".env.local").write_text("token=changed-local\n")
    (data / ".private-words").write_text("changed local private marker\n")
    git("commit", "-qm", "change owned site config", cwd=source)
    (data / "published").mkdir()
    (data / "published" / "signals.json").write_text(OWNED_CHANGES["published/signals.json"])
    (data / "runs" / "ignored-transcript.md").write_text("untracked raw transcript stays local\n")
    sibling = source / "research" / "dirty.txt"
    sibling.parent.mkdir()
    sibling.write_text("leave another writer alone\n")


def test_branch_delta_lands_on_private_main_without_touching_checkout_or_siblings(private_source):
    origin, source, data, code = private_source
    edit_branch_delta(source, data)
    expected = owned_tree_after(origin, OWNED_CHANGES)
    state_before = checkout_state(source)

    result = invoke(source, data, code, "--expect-tree", expected, "land the current edition")

    assert result.returncode == 0, result.stderr
    main = git("rev-parse", "refs/remotes/origin/main", cwd=source)
    assert main == git("rev-parse", "refs/heads/main", cwd=origin)
    assert f"[data] main: {main}" in result.stdout
    assert f"[data] owned tree: {expected}" in result.stdout
    assert git("rev-parse", f"{main}:sigma", cwd=origin) == expected
    assert checkout_state(source) == state_before


def test_a_plan_names_the_main_and_tree_a_landing_would_make_and_writes_nothing(private_source):
    origin, source, data, code = private_source
    edit_branch_delta(source, data)
    expected = owned_tree_after(origin, OWNED_CHANGES)
    state_before = checkout_state(source)
    remote_main_before = git("rev-parse", "refs/heads/main", cwd=origin)

    plan = invoke(source, data, code, "--plan")

    assert plan.returncode == 0, plan.stderr
    assert f"[data] main: {remote_main_before}" in plan.stdout
    assert f"[data] owned tree: {expected}" in plan.stdout
    assert git("rev-parse", "refs/heads/main", cwd=origin) == remote_main_before
    assert checkout_state(source) == state_before


def test_conflict_with_new_private_main_stops_without_changing_source(private_source, tmp_path):
    origin, source, data, code = private_source
    (data / "site.json").write_text('{"version":"ingest"}\n')
    git("add", "sigma/site.json", cwd=source)
    git("commit", "-qm", "ingest site config", cwd=source)
    sibling = source / "research" / "keep.txt"
    sibling.parent.mkdir()
    sibling.write_text("unrelated dirty file\n")
    other = tmp_path / "concurrent-main"
    git("clone", "-q", str(origin), str(other), cwd=tmp_path)
    (other / "sigma" / "site.json").write_text('{"version":"main"}\n')
    git("add", "sigma/site.json", cwd=other)
    git("commit", "-qm", "concurrent main change", cwd=other)
    git("push", "-q", "origin", "main", cwd=other)
    state_before = checkout_state(source)
    result = invoke(source, data, code, "conflicting landing")
    assert result.returncode == 1
    assert "conflicts with private main" in result.stderr
    assert checkout_state(source) == state_before
    main = git("rev-parse", "refs/heads/main", cwd=origin)
    assert git("show", f"{main}:sigma/site.json", cwd=origin) == '{"version":"main"}'


def test_private_data_refusals_leave_staged_files_and_remote_unchanged(private_source):
    origin, source, data, code = private_source
    remote_main_before = git("rev-parse", "refs/heads/main", cwd=origin)
    staged = source / "research" / "staged.json"
    staged.parent.mkdir()
    staged.write_text("keep staged\n")
    git("add", "research/staged.json", cwd=source)
    before = checkout_state(source)
    result = invoke(source, data, code)
    assert result.returncode == 1
    assert "pre-existing staged files" in result.stderr
    assert checkout_state(source) == before
    git("reset", "-q", "HEAD", "--", "research/staged.json", cwd=source)
    (data / "site.json").unlink()
    before = checkout_state(source)
    deleted = invoke(source, data, code)
    assert deleted.returncode == 1
    assert "delete private data without a saved copy" in deleted.stderr
    assert checkout_state(source) == before
    (data / "site.json").write_text('{"version":1}\n')
    (data / "published").mkdir()
    (data / "published" / "signals.json").write_text('{"signals":1}\n')
    before = checkout_state(source)
    refused = invoke(source, data, code, "--expect-tree", "0" * 40, "land the current edition")
    assert refused.returncode == 1
    assert "does not match the approved tree" in refused.stderr
    assert checkout_state(source) == before
    assert git("rev-parse", "refs/heads/main", cwd=origin) == remote_main_before


def test_data_commit_refuses_private_path_in_linked_public_worktree(tmp_path):
    public, linked = tmp_path / "public", tmp_path / "linked"
    public.mkdir()
    git("init", "-q", "--initial-branch=main", cwd=public)
    script = public / "deploy/mac/data-commit.sh"
    script.parent.mkdir(parents=True)
    shutil.copy(SCRIPT, script)
    git("add", "deploy/mac/data-commit.sh", cwd=public)
    git("commit", "-qm", "fixture", cwd=public)
    before = git("rev-parse", "HEAD", cwd=public)
    public_data = public / "private-data"
    public_data.mkdir()
    refused = invoke(public, public_data, public, "must refuse public repository data")
    assert refused.returncode == 1
    assert "public Sigma repository" in refused.stderr
    assert git("rev-parse", "HEAD", cwd=public) == before and git("diff", "--cached", cwd=public) == ""
    git("worktree", "add", "-q", "-b", "linked-data", str(linked), "main", cwd=public)
    data = linked / "private-data"
    data.mkdir()
    (data / "site.json").write_text('{"site_name":"Sigma"}')
    assert common_dir(public) == common_dir(linked)
    result = invoke(public, data, public, "must refuse linked checkout data")
    assert result.returncode == 1
    assert "linked checkout of the public Sigma repository" in result.stderr
    assert git("diff", "--cached", cwd=linked) == ""
    assert git("rev-parse", "HEAD", cwd=linked) == before
