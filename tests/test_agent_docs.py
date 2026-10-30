from pathlib import Path

import pytest

from tests.helpers import load_script

check = load_script("check_agent_docs")
SKILL = "---\nname: demo\ndescription: Does the demo thing.\n---\nBody.\n"


def build(root: Path) -> Path:
    (root / "docs").mkdir()
    (root / "docs" / "a.md").write_text("a\n")
    (root / "AGENTS.md").write_text("# Map\n- [a](docs/a.md)\n- [site](https://example.com/x)\n- [top](#map)\n")
    (root / "skills" / "demo").mkdir(parents=True)
    (root / "skills" / "demo" / "SKILL.md").write_text(SKILL)
    (root / ".claude" / "skills").mkdir(parents=True)
    (root / ".claude" / "skills" / "demo").symlink_to("../../skills/demo")
    return root


def run(root: Path, capsys):
    code = check.main([str(root)])
    return code, capsys.readouterr().err


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


def test_a_healthy_tree_passes_and_agents_md_may_be_exactly_8000_chars(tmp_path, capsys):
    """Rule: AGENTS.md is at most 8k; the limit itself is allowed."""
    root = build(tmp_path)
    pad_agents(root, 8_000)
    assert run(root, capsys)[0] == 0


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
    ],
    ids=["agents-too-long", "dead-link", "name-not-folder", "no-description", "skill-too-long", "dangling-symlink",
         "second-copy"],
)
def test_each_rule_breaks_the_check_and_names_the_file_to_fix(tmp_path, capsys, break_it, names):
    """Rules: AGENTS.md at most 8k, map links exist, skill name matches its folder and has a description, a skill
    is at most 12k, .claude/skills holds only symlinks that resolve."""
    root = build(tmp_path)
    break_it(root)
    code, err = run(root, capsys)
    assert code == 1
    assert names in err
