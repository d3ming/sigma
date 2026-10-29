import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "deploy" / "mac" / "site-deploy.sh"
pytestmark = pytest.mark.skipif(shutil.which("zsh") is None, reason="site-deploy.sh is a zsh script")
FAKE = """#!/bin/sh
case "$1" in
  build)
    [ "$2" = "--prod" ] || exit 8
    echo build >> "$FAKE_BUILD_LOG"
    [ -f "$SIGMA_DATA_ROOT/site.json" ] && grep -q 'Sigma fixture' "$SIGMA_DATA_ROOT/site.json" || exit 12
    if [ "${FAKE_REQUIRE_FROZEN:-0}" = "1" ]; then
      [ "$SIGMA_DATA_ROOT" != "$FAKE_ORIGINAL_DATA_ROOT" ] && [ ! -e "$SIGMA_DATA_ROOT/private-input" ] && \
        [ "$SIGMA_SITE_CONFIG" = "$SIGMA_DATA_ROOT/site.json" ] && [ "$SIGMA_X_DIR" = "$SIGMA_DATA_ROOT/x" ] || exit 12
    fi
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
        self.clone, bin_ = tmp_path / "clone", tmp_path / "bin"
        self.clone.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        (self.clone / "deploy/mac").mkdir(parents=True)
        shutil.copy(SCRIPT, self.clone / "deploy/mac/site-deploy.sh")
        shutil.copytree(Path(__file__).parent.parent / "sigma", self.clone / "sigma",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copytree(Path(__file__).parent.parent / "schema", self.clone / "schema",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        (self.clone / "index.txt").write_text("site")
        (self.clone / ".vercel").mkdir()
        (self.clone / ".vercel/project.json").write_text("{}")
        self.git("add", "-A")
        self.git("commit", "-qm", "fixture")
        bin_.mkdir()
        (bin_ / "vercel").write_text(FAKE)
        (bin_ / "vercel").chmod(0o755)
        self.upload_log = tmp_path / "uploads.txt"
        self.build_log = tmp_path / "builds.txt"
        data_root = tmp_path / "private-data"
        self.data_root = data_root
        data_root.mkdir()
        (data_root / "site.json").write_text('{"site_name":"Sigma fixture","base_url":"https://sigma.example"}\n')
        (data_root / "private-input").write_text("must not reach the build snapshot")
        from sigma import published
        from tests.test_links import make_run

        run = make_run(data_root)
        published.export(run, root=data_root / "published", resolver=False)
        self.env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "FAKE_CONTENT": "site",
                    "SIGMA_BASE_URL": "https://sigma.example",
                    "SIGMA_DATA_ROOT": str(data_root), "SIGMA_PYTHON": sys.executable,
                    "FAKE_ORIGINAL_DATA_ROOT": str(data_root),
                    "SIGMA_PUBLICATION_DATA_SNAPSHOT_ROOT": str(tmp_path / "snapshots"),
                    "FAKE_UPLOAD_LOG": str(self.upload_log), "FAKE_BUILD_LOG": str(self.build_log)}

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
    site.env["FAKE_PRIVATE_OUTPUT"] = "1"
    site.env["FAKE_REQUIRE_FROZEN"] = "1"
    refused = site.run("--preflight")
    assert refused.returncode == 1 and "source-grounded publication inputs accepted" in refused.stdout
    assert "generated publication contains a private path" in refused.stderr
    assert not site.upload_log.exists()
    assert not (site.clone / ".vercel/deployed-hash").exists()
    before = site.build_log.read_text()
    from sigma import published

    episodes = site.data_root / "published" / "weekly" / "episodes.json"
    episodes_before = episodes.read_bytes()
    episode_rows = json.loads(episodes.read_text())
    episode_rows[0]["API_KEY"] = "sk_test_0123456789abcdef"
    episodes.write_text(json.dumps(episode_rows) + "\n")
    with pytest.raises(ValueError, match="public file looks private"):
        published.validate_publication_privacy(site.data_root / "published")
    assert site.build_log.read_text() == before
    episodes.write_bytes(episodes_before)
    episode_rows = json.loads(episodes_before)
    episode_rows[0]["url"] = "https://example.com/replaced"
    episodes.write_text(json.dumps(episode_rows) + "\n")
    with pytest.raises(ValueError, match="episodes.json differs from source run"):
        published.validate_publication_inputs(site.data_root / "published", site.data_root / "runs")
    assert site.build_log.read_text() == before
    episodes.write_bytes(episodes_before)
    claims = site.data_root / "published" / "weekly" / "claims.jsonl"
    rows = [json.loads(line) for line in claims.read_text().splitlines()]
    rows[0]["text"] += " changed"
    claims.write_text("".join(json.dumps(row) + "\n" for row in rows))
    site.env.pop("FAKE_PRIVATE_OUTPUT")
    tampered = site.run("--preflight")
    assert tampered.returncode != 0 and "claims.jsonl differs from validated source" in tampered.stderr
    assert site.build_log.read_text() == before
    assert not site.upload_log.exists()
