#!/usr/bin/env python3
"""Fail when an agent-facing document would be cut off, misnamed or point at nothing.

An agent loads AGENTS.md whole, and a loader truncates a file that is too long, so the rules at its end go unread:
AGENTS.md stays within AGENTS_MAX characters and each SKILL.md within SKILL_MAX. CLAUDE.md only forwards to AGENTS.md.
Every relative link in AGENTS.md must exist. Each skills/<name>/SKILL.md names itself <name> and has a description.
Every .claude/skills/<name> is a symlink to a skills/ folder that holds a SKILL.md, so a skill has one home.

    python3 scripts/check_agent_docs.py [ROOT]

Exit 0 when everything holds, 1 with one `path: problem` line each otherwise.
"""
import re
import sys
from pathlib import Path

import yaml

AGENTS_MAX = 8_000
SKILL_MAX = 12_000
LINK = re.compile(r"\]\(([^)\s]+)\)")
EXTERNAL = re.compile(r"[a-z][a-z0-9+.-]*:|#")


def frontmatter(text: str) -> dict:
    parts = text.split("---", 2)
    if not text.startswith("---") or len(parts) < 3:
        return {}
    meta = yaml.safe_load(parts[1])
    return meta if isinstance(meta, dict) else {}


def skill_problems(folder: Path) -> list[str]:
    rel = f"skills/{folder.name}/SKILL.md"
    skill = folder / "SKILL.md"
    if not skill.is_file():
        return [f"{rel}: missing"]
    text = skill.read_text(encoding="utf-8")
    meta = frontmatter(text)
    found = []
    if len(text) > SKILL_MAX:
        found.append(f"{rel}: {len(text)} chars, over {SKILL_MAX}")
    if meta.get("name") != folder.name:
        found.append(f"{rel}: frontmatter name must be {folder.name}")
    if not str(meta.get("description") or "").strip():
        found.append(f"{rel}: frontmatter description is missing")
    return found


def problems(root: Path) -> list[str]:
    found = []
    agents = root / "AGENTS.md"
    text = agents.read_text(encoding="utf-8") if agents.is_file() else ""
    if not text:
        found.append("AGENTS.md: missing or empty")
    if len(text) > AGENTS_MAX:
        found.append(f"AGENTS.md: {len(text)} chars, over {AGENTS_MAX}")
    claude = root / "CLAUDE.md"
    if not claude.is_file() or claude.read_text(encoding="utf-8").strip() != "@AGENTS.md":
        found.append("CLAUDE.md: must contain only @AGENTS.md")
    for target in LINK.findall(text):
        path = target.split("#")[0]
        if path and not EXTERNAL.match(target) and not (root / path).exists():
            found.append(f"AGENTS.md: link to {path} points at nothing")
    for folder in sorted((root / "skills").glob("*/")):
        found += skill_problems(folder)
    for link in sorted((root / ".claude" / "skills").glob("*")):
        rel = f".claude/skills/{link.name}"
        target = link.resolve()
        if target.parent != (root / "skills").resolve() or not (target / "SKILL.md").is_file():
            found.append(f"{rel}: must be a symlink to a skills/ folder holding SKILL.md")
    return found


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent)
    found = problems(root)
    if found:
        print("\n".join(found), file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
