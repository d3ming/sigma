import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "deploy" / "mac" / "site-deploy.sh"
pytestmark = pytest.mark.skipif(shutil.which("zsh") is None, reason="site-deploy.sh is a zsh script")
FAKE = """#!/bin/sh
case "$1" in
  build)
    [ "$2" = "--prod" ] || exit 8
    [ "$SIGMA_DATA_ROOT" = "$FAKE_EXPECTED_DATA_ROOT" ] && [ -f "$SIGMA_DATA_ROOT/site-marker" ] || exit 12
    for path in .env.local .private-words PLAN.md docs/migration/private.md data/site.json followlists.yaml; do
      [ ! -e "$path" ] || { echo "private source path reached Vercel build" >&2; exit 11; }
    done
    mkdir -p .vercel/output/static
    printf '{}\n' > .vercel/output/config.json
    printf '%s\n' "${FAKE_CONTENT:-site}" > .vercel/output/static/index.html
    if [ "${FAKE_PRIVATE_OUTPUT:-0}" = "1" ]; then
      printf 'fixture-secret\n' > .vercel/output/static/.env.local
      printf 'fixture-private-words\n' > .vercel/output/static/.private-words
      printf 'fixture-plan\n' > .vercel/output/static/PLAN.md
      printf 'fixture-followlist\n' > .vercel/output/static/followlists.json
    fi
    echo "Built production output"
    exit 0
    ;;
  deploy)
    [ "$2" = "--prebuilt" ] && [ "$3" = "--prod" ] && [ "$4" = "--yes" ] || exit 9
    [ -f .vercel/output/config.json ] || exit 10
    echo "upload attempted" > "$FAKE_UPLOAD_LOG"
    echo "https://sigma-test.vercel.app"
    ;;
esac
"""
class Site:
    def __init__(self, tmp_path):
        origin, self.clone, bin_ = tmp_path / "origin.git", tmp_path / "clone", tmp_path / "bin"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
        subprocess.run(["git", "clone", "-q", str(origin), str(self.clone)], check=True, capture_output=True)
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        (self.clone / "deploy/mac").mkdir(parents=True)
        shutil.copy(SCRIPT, self.clone / "deploy/mac/site-deploy.sh")
        (self.clone / "index.txt").write_text("site")
        (self.clone / ".vercel").mkdir()
        (self.clone / ".vercel/project.json").write_text("{}")
        self.git("add", "-A")
        self.git("commit", "-qm", "fixture")
        self.git("push", "-q", "-u", "origin", "main")
        bin_.mkdir()
        (bin_ / "vercel").write_text(FAKE)
        (bin_ / "vercel").chmod(0o755)
        self.upload_log = tmp_path / "uploads.txt"
        data_root = tmp_path / "private-data"
        data_root.mkdir()
        (data_root / "site-marker").write_text("private data supplied outside source archive")
        self.env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "FAKE_CONTENT": "site",
                    "SIGMA_BASE_URL": "https://sigma.example",
                    "SIGMA_DATA_ROOT": str(data_root), "FAKE_EXPECTED_DATA_ROOT": str(data_root),
                    "FAKE_UPLOAD_LOG": str(self.upload_log)}

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.clone, check=True, capture_output=True, text=True).stdout.strip()

    def run(self, *args):
        return subprocess.run(["zsh", str(self.clone / "deploy/mac/site-deploy.sh"), *args], cwd=self.clone,
                              env=self.env, capture_output=True, text=True)


def test_private_source_and_generated_paths_are_refused_before_upload(tmp_path):
    site = Site(tmp_path)
    for name in (".env.local", ".private-words", "PLAN.md", "docs/migration/private.md", "data/site.json", "followlists.yaml"):
        path = site.clone / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture-secret")
    built = site.run("--dry-run")
    assert built.returncode == 0 and "production build content:" in built.stdout
    assert "no deployment uploaded" in built.stdout
    assert "private source path reached" not in built.stderr
    site.env["FAKE_PRIVATE_OUTPUT"] = "1"
    refused = site.run("--preflight")
    assert refused.returncode == 1 and "generated publication contains a private path" in refused.stderr
    assert not site.upload_log.exists()
    assert not (site.clone / ".vercel/deployed-hash").exists()
