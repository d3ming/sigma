import re
import subprocess
from pathlib import Path

import pytest

from tests.helpers import load_script

ROOT = Path(__file__).resolve().parent.parent
gate_script = load_script("check_rubric_bump")
SCHEMA = re.compile(r"schema/([\w.-]+\.schema\.json)")
VERSION_LINE = re.compile(r"^Rubric version: \d+$", re.M)


def test_every_schema_a_prompt_names_exists():
    """Rule (CONTRIBUTING): an agent's output has a schema in schema/; a prompt that names a missing one is unusable."""
    missing = [
        f"{prompt.name} -> {name}"
        for prompt in sorted((ROOT / "prompts").glob("*.md"))
        for name in SCHEMA.findall(prompt.read_text())
        if not (ROOT / "schema" / name).is_file()
    ]
    assert missing == []


def test_each_ranking_prompt_has_exactly_one_version_line():
    """Rule: sigma.rank.rubric_version takes the first `Rubric version: N` line, so a second line is silently ignored."""
    prompts = sorted((ROOT / "prompts").glob("rank*.md"))
    assert {p.name for p in prompts} >= {"rank.md", "rank-influencer.md"}
    assert {p.name: len(VERSION_LINE.findall(p.read_text())) for p in prompts} == {p.name: 1 for p in prompts}


def commit(repo: Path, text: str, message: str = "change"):
    (repo / "prompts" / "rank.md").write_text(text)
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com"]
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run([*git, "commit", "-q", "-m", message], cwd=repo, check=True)


@pytest.fixture
def gate(monkeypatch, capsys):
    def run(repo: Path, base: str = "BASE", head: str = "HEAD"):
        monkeypatch.chdir(repo)
        code = gate_script.main([base, head])
        return code, capsys.readouterr().err

    return run


def rubric_repo(repo: Path) -> Path:
    (repo / "prompts").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    commit(repo, "Rubric version: 2\n\nScore 1 to 5.\n", "base")
    subprocess.run(["git", "tag", "BASE"], cwd=repo, check=True)
    return repo


def test_a_changed_ranking_prompt_needs_a_higher_version(tmp_path, gate):
    """Rule: scores are reused only within a rubric version, so changing the rubric text must bump the version."""
    repo = rubric_repo(tmp_path)
    assert gate(repo)[0] == 0

    commit(repo, "Rubric version: 2\n\nScore 1 to 10.\n")
    code, err = gate(repo)
    assert code == 1
    assert "prompts/rank.md" in err

    commit(repo, "Rubric version: 3\n\nScore 1 to 10.\n")
    assert gate(repo)[0] == 0

    commit(repo, "Score 1 to 10.\n")
    code, err = gate(repo)
    assert code == 1
    assert "prompts/rank.md" in err.splitlines()[0]


def test_a_waiver_covers_only_the_file_it_names(tmp_path, gate):
    """Rule: a wording change that cannot move a score is waived per file, with a reason, in a commit message."""
    named = rubric_repo(tmp_path / "named")
    commit(named, "Rubric version: 2\n\nScore 1 to 5, typo fixed.\n",
           "fix\n\nRubric-unchanged: prompts/rank.md wording only\n")
    other = rubric_repo(tmp_path / "other")
    commit(other, "Rubric version: 2\n\nScore 1 to 5, typo fixed.\n",
           "fix\n\nRubric-unchanged: prompts/rank-influencer.md wording only\n")
    assert (gate(named)[0], gate(other)[0]) == (0, 1)


def test_a_branch_is_judged_against_where_it_left_the_base_branch(tmp_path, gate):
    """Rule: a release PR is judged on what it adds; a rubric bump that landed on the base after the branch left is not its change."""
    repo = rubric_repo(tmp_path)
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com"]
    subprocess.run(["git", "switch", "-q", "-c", "topic"], cwd=repo, check=True)
    (repo / "notes.md").write_text("n\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run([*git, "commit", "-q", "-m", "notes"], cwd=repo, check=True)
    subprocess.run(["git", "switch", "-q", "main"], cwd=repo, check=True)
    commit(repo, "Rubric version: 3\n\nScore 1 to 10.\n")
    assert gate(repo, "main", "topic")[0] == 0
