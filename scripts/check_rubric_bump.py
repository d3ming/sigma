#!/usr/bin/env python3
"""Fail when a ranking prompt changed without a higher `Rubric version:`.

Scores are reused only within a rubric version, so a rubric change that keeps its version leaves the library scored
under two rubrics with one label. Compares prompts/rank*.md at HEAD with the merge base of BASE and HEAD. A wording change that cannot move a score
(and so must not re-score the library) is waived per file by a line `Rubric-unchanged: prompts/rank.md <reason>` in the
body of a commit in the range.

    python3 scripts/check_rubric_bump.py BASE [HEAD]

Exit 0 when every changed ranking prompt has a higher version, 1 with one line per prompt that does not.
"""
import re
import subprocess
import sys

VERSION = re.compile(r"^Rubric version: (\d+)", re.M)
WAIVER = re.compile(r"^Rubric-unchanged: (\S+) \S.*$", re.M)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def version(text: str) -> int | None:
    m = VERSION.search(text)
    return int(m.group(1)) if m else None


def problems(base: str, head: str) -> list[str]:
    point = git("merge-base", base, head).strip()
    waived = set(WAIVER.findall(git("log", "--format=%B", f"{point}..{head}")))
    found = []
    for path in git("diff", "--name-only", point, head, "--", "prompts/rank*.md").split():
        if path in waived:
            continue
        before = subprocess.run(["git", "show", f"{point}:{path}"], capture_output=True, text=True)
        after = git("show", f"{head}:{path}")
        old = version(before.stdout) if before.returncode == 0 else None
        new = version(after)
        if new is None:
            found.append(f"{path}: has no `Rubric version: N` line")
        elif old is not None and new <= old:
            found.append(f"{path}: changed but Rubric version is still {new}; bump it so the library re-scores")
    return found


def main() -> int:
    found = problems(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "HEAD")
    if found:
        print("\n".join(found), file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
