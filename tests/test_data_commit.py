import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "deploy" / "mac" / "data-commit.sh"
pytestmark = pytest.mark.skipif(shutil.which("zsh") is None, reason="data-commit.sh is a zsh script")


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def common_dir(repo):
    value = Path(git("rev-parse", "--git-common-dir", cwd=repo))
    return (value if value.is_absolute() else repo / value).resolve()


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
    git("worktree", "add", "-q", "-b", "linked-data", str(linked), "main", cwd=public)
    git("branch", "--set-upstream-to=origin/main", "linked-data", cwd=public)
    data = linked / "private-data"
    data.mkdir()
    (data / "site.json").write_text('{"site_name":"Sigma"}\n')
    assert common_dir(public) == common_dir(linked)
    before = git("rev-parse", "origin/main", cwd=public)
    result = subprocess.run(["zsh", str(script), "must refuse linked checkout data"], cwd=public,
                            env={**os.environ, "SIGMA_DATA_ROOT": str(data)}, capture_output=True, text=True)
    assert result.returncode == 1
    assert "linked checkout of the public Sigma repository" in result.stderr
    assert subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=linked).returncode == 0
    assert git("rev-parse", "origin/main", cwd=public) == before
    assert git("rev-parse", "HEAD", cwd=linked) == before
