import subprocess
import sys
from pathlib import Path

import pytest

CHECK = Path(__file__).resolve().parent.parent / "scripts" / "check_agent_docs.py"
SKILL = "---\nname: demo\ndescription: Does the demo thing.\n---\nBody.\n"


def build(root: Path) -> Path:
    (root / "docs").mkdir()
    (root / "docs" / "a.md").write_text("a\n")
    (root / "AGENTS.md").write_text("# Map\n- [a](docs/a.md)\n- [site](https://example.com/x)\n- [top](#map)\n")
    (root / "CLAUDE.md").write_text("@AGENTS.md\n")
    (root / "skills" / "demo").mkdir(parents=True)
    (root / "skills" / "demo" / "SKILL.md").write_text(SKILL)
    (root / ".claude" / "skills").mkdir(parents=True)
    (root / ".claude" / "skills" / "demo").symlink_to("../../skills/demo")
    return root


def run(root: Path):
    return subprocess.run([sys.executable, str(CHECK), str(root)], capture_output=True, text=True)


def pad_agents(root: Path, size: int):
    (root / "AGENTS.md").write_text("x" * size)


def dead_link(root: Path):
    (root / "AGENTS.md").write_text("[gone](docs/gone.md)\n")


def skill_in_wrong_folder(root: Path):
    (root / "skills" / "demo" / "SKILL.md").write_text(SKILL.replace("name: demo", "name: other"))


def skill_without_description(root: Path):
    (root / "skills" / "demo" / "SKILL.md").write_text("---\nname: demo\n---\nBody.\n")


def oversized_skill(root: Path):
    (root / "skills" / "demo" / "SKILL.md").write_text(SKILL + "x" * 12_000)


def dangling_symlink(root: Path):
    (root / ".claude" / "skills" / "demo").unlink()
    (root / ".claude" / "skills" / "demo").symlink_to("../../skills/gone")


def second_home(root: Path):
    (root / ".claude" / "skills" / "demo").unlink()
    (root / ".claude" / "skills" / "demo").mkdir()
    (root / ".claude" / "skills" / "demo" / "SKILL.md").write_text(SKILL)


def claude_forks_agents(root: Path):
    (root / "CLAUDE.md").write_text("# Own rules\n")


def test_a_healthy_tree_passes_and_agents_md_may_be_exactly_8000_chars(tmp_path):
    """Rule: AGENTS.md is at most 8k; the limit itself is allowed."""
    root = build(tmp_path)
    pad_agents(root, 8_000)
    assert run(root).returncode == 0


@pytest.mark.parametrize(
    "break_it, names",
    [
        (lambda r: pad_agents(r, 8_001), "AGENTS.md"),
        (dead_link, "docs/gone.md"),
        (skill_in_wrong_folder, "skills/demo/SKILL.md"),
        (skill_without_description, "skills/demo/SKILL.md"),
        (oversized_skill, "skills/demo/SKILL.md"),
        (dangling_symlink, ".claude/skills/demo"),
        (second_home, ".claude/skills/demo"),
        (claude_forks_agents, "CLAUDE.md"),
    ],
    ids=["agents-too-long", "dead-link", "name-not-folder", "no-description", "skill-too-long", "dangling-symlink",
         "second-copy", "claude-forks-agents"],
)
def test_each_rule_breaks_the_check_and_names_the_file_to_fix(tmp_path, break_it, names):
    """Rules: AGENTS.md at most 8k, map links exist, skill name matches its folder and has a description, a skill
    is at most 12k, .claude/skills holds only symlinks that resolve, CLAUDE.md is only @AGENTS.md."""
    root = build(tmp_path)
    break_it(root)
    result = run(root)
    assert result.returncode == 1
    assert names in result.stderr
