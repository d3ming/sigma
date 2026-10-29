"""deploy/mac/site-deploy.sh: a failed `vercel deploy` is never silent (it prints the exit code and both streams), is retried
once, a deploy whose URL is on stdout is stamped, and a Pacific day allows two of them. A fake `vercel` on PATH stands in for the CLI."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "deploy" / "mac" / "site-deploy.sh"
pytestmark = pytest.mark.skipif(shutil.which("zsh") is None, reason="site-deploy.sh is a zsh script")

# FAKE_VERCEL: space-separated outcomes per call: ok, die (exit 3, only a banner on stderr), err (stderr text, exit 1),
# late (a URL on stdout, then the build fails: exit 1).
FAKE = """#!/bin/sh
case "$1" in --version) echo "Vercel CLI 0.0.0-test"; exit 0;; esac
n=$(cat "$FAKE_STATE" 2>/dev/null || echo 0); n=$((n+1)); echo $n >"$FAKE_STATE"
set -- $FAKE_VERCEL; eval "o=\\${$n:-die}"
case "$o" in
  ok) echo "Deploying wire" >&2; echo "https://wire-test-abc.vercel.app"; exit 0;;
  late) echo "https://wire-test-bad.vercel.app"; echo "Error: build failed" >&2; exit 1;;
  err) echo "Error: upload failed (ECONNRESET)" >&2; exit 1;;
  *) echo "Vercel CLI 0.0.0-test" >&2; echo "Deploying wire" >&2; exit 3;;
esac
"""


class Site:
    """A bare origin, a clone on main with a Vercel link, and a fake vercel on PATH."""

    def __init__(self, tmp_path, outcomes):
        origin, self.clone, bin_ = tmp_path / "origin.git", tmp_path / "clone", tmp_path / "bin"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
        subprocess.run(["git", "clone", "-q", str(origin), str(self.clone)], check=True, capture_output=True)
        self.git("config", "user.email", "t@example.com"); self.git("config", "user.name", "t")
        (self.clone / "deploy" / "mac").mkdir(parents=True)
        shutil.copy(SCRIPT, self.clone / "deploy" / "mac" / "site-deploy.sh")
        (self.clone / ".gitignore").write_text(".vercel\n")  # as in the repo
        self.commit("index.txt", "site")
        (self.clone / ".vercel").mkdir()
        (self.clone / ".vercel" / "project.json").write_text("{}")
        bin_.mkdir()
        (bin_ / "vercel").write_text(FAKE)
        (bin_ / "vercel").chmod(0o755)
        self.state = tmp_path / "n"
        self.env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "FAKE_VERCEL": outcomes, "FAKE_STATE": str(self.state),
                    "WIRE_DEPLOY_RETRY_SLEEP": "0"}

    def git(self, *a):
        return subprocess.run(["git", *a], cwd=self.clone, check=True, capture_output=True, text=True).stdout.strip()

    def commit(self, path, text):
        (self.clone / path).parent.mkdir(parents=True, exist_ok=True)
        (self.clone / path).write_text(text)
        self.git("add", "-A"); self.git("commit", "-qm", f"change {path}"); self.git("push", "-q", "origin", "main")

    def run(self, *args):
        return subprocess.run(["zsh", str(self.clone / "deploy" / "mac" / "site-deploy.sh"), *args], cwd=self.clone, env=self.env,
                              capture_output=True, text=True)

    @property
    def calls(self):
        return int(self.state.read_text()) if self.state.exists() else 0

    @property
    def deploys(self):
        f = self.clone / ".vercel" / "deploys"
        return f.read_text().splitlines() if f.exists() else []


def test_a_deploy_that_dies_silently_prints_what_it_has_and_is_retried_once(tmp_path):
    site = Site(tmp_path, "die ok")
    r = site.run("--force")
    assert r.returncode == 0 and site.calls == 2, r.stdout + r.stderr
    assert "attempt 1 failed (vercel exit 3)" in r.stderr  # the exit code the old script threw away
    assert "Deploying wire" in r.stderr and "retrying once" in r.stderr
    assert "[site] deployed" in r.stdout and "https://wire-test-abc.vercel.app" in r.stdout
    assert (site.clone / ".vercel" / "deployed-sha").read_text().strip()  # stamped, so no later run deploys it again
    assert "vercel exit 3" in (site.clone / ".vercel" / "deploy-failed.log").read_text()


def test_two_failures_exit_nonzero_with_the_error_text_and_no_stamp(tmp_path):
    site = Site(tmp_path, "late err")
    r = site.run("--force")
    assert r.returncode == 1 and site.calls == 2
    assert "deploy failed twice (vercel exit 1)" in r.stdout and "ECONNRESET" in r.stdout
    assert len(site.deploys) == 1  # the failed build did create a deployment: it counts
    assert "attempt 1 failed (vercel exit 1)" in r.stderr and "[site] deployed" not in r.stdout  # a URL from a build that then failed is no success
    assert not (site.clone / ".vercel" / "deployed-sha").exists()


def test_a_failed_build_that_used_the_last_deploy_is_not_retried(tmp_path):
    site = Site(tmp_path, "late ok")
    (site.clone / ".vercel" / "deploys").write_text(f"{__import__('datetime').datetime.now(__import__('zoneinfo').ZoneInfo('America/Los_Angeles')):%F} abc\n")
    r = site.run()
    assert r.returncode == 1 and site.calls == 1 and "not retrying" in r.stderr, r.stdout + r.stderr


def test_a_clean_deploy_makes_one_call_and_leaves_no_failure_log(tmp_path):
    site = Site(tmp_path, "ok")
    (site.clone / ".vercel" / "deploys").write_text("2020-01-01 abc\n2020-01-01 def\n")  # yesterday's deploys do not count
    r = site.run()
    assert r.returncode == 0 and site.calls == 1 and "retrying" not in r.stderr
    assert not (site.clone / ".vercel" / "deploy-failed.log").exists()


def test_a_pacific_day_allows_two_deploys_and_refuses_the_third(tmp_path):
    site = Site(tmp_path, "ok ok ok")
    assert site.run().returncode == 0 and site.deploys  # the 8:00 AM publish
    site.commit("a.txt", "x")
    assert site.run().returncode == 0 and len(site.deploys) == 2  # the 5:00 PM publish
    site.commit("b.txt", "y")
    r = site.run()
    assert r.returncode == 1 and site.calls == 2, r.stdout + r.stderr
    assert "already made today's 2 deploys" in r.stdout
    assert site.run("--quota", "origin/main").returncode == 1  # release.sh land asks this before it moves main
    assert site.run("--force").returncode == 0 and site.calls == 3 and len(site.deploys) == 3  # the owner's ask lifts it, counted


def test_a_commit_the_site_does_not_read_needs_no_deploy_even_when_the_day_is_used_up(tmp_path):
    site = Site(tmp_path, "ok ok")
    for i in range(2):
        site.commit(f"f{i}.txt", "x")
        assert site.run().returncode == 0
    site.commit("docs/notes.md", "words")
    assert site.run("--quota", "origin/main").returncode == 0  # nothing the build reads changed: land may proceed
    r = site.run()
    assert r.returncode == 0 and "not deployed" in r.stdout and site.calls == 2
