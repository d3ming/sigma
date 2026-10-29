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
    [ "${FAKE_BUILD:-ok}" = "ok" ] || { echo "build failed" >&2; exit 2; }
    [ "$SIGMA_DATA_ROOT" = "$FAKE_EXPECTED_DATA_ROOT" ] && [ -f "$SIGMA_DATA_ROOT/site-marker" ] || exit 12
    for path in .env.local .private-words PLAN.md docs/migration/private.md data/site.json followlists.yaml; do
      [ ! -e "$path" ] || { echo "private source path reached Vercel build" >&2; exit 11; }
    done
    n=$(cat "$FAKE_BUILD_STATE" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "$FAKE_BUILD_STATE"
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
    n=$(cat "$FAKE_STATE" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "$FAKE_STATE"
    set -- $FAKE_DEPLOY
    case "${1:-ok}" in
      ok) echo "https://sigma-test-$n.vercel.app"; exit 0 ;;
      err) echo "upload failed" >&2; exit 1 ;;
      urlerr) echo "https://sigma-test-$n.vercel.app"; echo "upload failed after creation" >&2; exit 1 ;;
      urlerr-once) if [ "$n" = 1 ]; then echo "https://sigma-test-$n.vercel.app"; echo "upload failed after creation" >&2; exit 1; fi; echo "https://sigma-test-$n.vercel.app"; exit 0 ;;
    esac
    ;;
esac
"""
class Site:
    def __init__(self, tmp_path, deploy="ok", build="ok"):
        origin, self.clone, bin_ = tmp_path / "origin.git", tmp_path / "clone", tmp_path / "bin"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
        subprocess.run(["git", "clone", "-q", str(origin), str(self.clone)], check=True, capture_output=True)
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        (self.clone / "deploy/mac").mkdir(parents=True)
        shutil.copy(SCRIPT, self.clone / "deploy/mac/site-deploy.sh")
        self.commit("index.txt", "site")
        (self.clone / ".vercel").mkdir()
        (self.clone / ".vercel/project.json").write_text("{}")
        bin_.mkdir()
        (bin_ / "vercel").write_text(FAKE)
        (bin_ / "vercel").chmod(0o755)
        self.state = tmp_path / "deploy-count"
        self.build_state = tmp_path / "build-count"
        data_root = tmp_path / "private-data"
        data_root.mkdir()
        (data_root / "site-marker").write_text("private data supplied outside source archive")
        self.env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "FAKE_DEPLOY": deploy,
                    "FAKE_BUILD": build, "FAKE_CONTENT": "site", "FAKE_STATE": str(self.state),
                    "FAKE_BUILD_STATE": str(self.build_state), "SIGMA_BASE_URL": "https://sigma.example",
                    "SIGMA_DATA_ROOT": str(data_root), "FAKE_EXPECTED_DATA_ROOT": str(data_root),
                    "SIGMA_DEPLOY_RETRY_SLEEP": "0"}

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.clone, check=True, capture_output=True, text=True).stdout.strip()

    def commit(self, name, value):
        (self.clone / name).write_text(value)
        self.git("add", "-A")
        self.git("commit", "-qm", f"change {name}")
        self.git("push", "-q", "origin", "main")

    def run(self, *args):
        return subprocess.run(["zsh", str(self.clone / "deploy/mac/site-deploy.sh"), *args], cwd=self.clone,
                              env=self.env, capture_output=True, text=True)

    @property
    def calls(self):
        return int(self.state.read_text()) if self.state.exists() else 0

    @property
    def deploys(self):
        path = self.clone / ".vercel/deploys"
        return path.read_text().splitlines() if path.exists() else []

    @property
    def builds(self):
        return int(self.build_state.read_text()) if self.build_state.exists() else 0


def test_dry_run_builds_and_hashes_without_upload(tmp_path):
    site = Site(tmp_path)
    result = site.run("--dry-run")
    assert result.returncode == 0 and "changed; dry run" in result.stdout
    assert "no deployment uploaded" in result.stdout and site.calls == 0
    content_hash = next(line.rsplit(" ", 1)[-1] for line in result.stdout.splitlines()
                        if line.startswith("[site] production build content: "))
    assert (site.clone / ".vercel/publication" / content_hash / ".vercel/output/config.json").exists()


def test_private_untracked_sources_are_absent_from_the_vercel_build_workspace(tmp_path):
    site = Site(tmp_path)
    for name in (".env.local", ".private-words", "PLAN.md", "docs/migration/private.md", "data/site.json", "followlists.yaml"):
        path = site.clone / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture-secret")
    result = site.run("--preflight")
    assert result.returncode == 0 and "production build content" in result.stdout
    assert "private source path reached" not in result.stderr and site.calls == 0


def test_relative_private_data_root_resolves_from_the_invoking_checkout(tmp_path):
    site = Site(tmp_path)
    data_root = site.clone / "private-inputs"
    data_root.mkdir()
    (data_root / "site-marker").write_text("private data")
    site.env["SIGMA_DATA_ROOT"] = "private-inputs"
    site.env["FAKE_EXPECTED_DATA_ROOT"] = str(data_root)
    result = site.run("--preflight")
    assert result.returncode == 0 and "production build content" in result.stdout


def test_generated_private_path_is_refused_before_upload(tmp_path):
    site = Site(tmp_path)
    site.env["FAKE_PRIVATE_OUTPUT"] = "1"
    result = site.run("--preflight")
    assert result.returncode == 1 and "generated publication contains a private path" in result.stderr
    assert site.calls == 0 and not (site.clone / ".vercel/deployed-hash").exists()


def test_preflight_refuses_a_changed_build_after_the_daily_quota(tmp_path):
    site = Site(tmp_path)
    for value in ("one", "two"):
        site.env["FAKE_CONTENT"] = value
        assert site.run().returncode == 0
    site.env["FAKE_CONTENT"] = "three"
    result = site.run("--preflight")
    assert result.returncode == 1 and "already made today's 2 deployments" in result.stderr
    assert site.calls == 2


def test_deploy_staged_uploads_the_preflight_artifact_without_rebuilding(tmp_path):
    site = Site(tmp_path)
    preflight = site.run("--preflight")
    assert preflight.returncode == 0 and site.builds == 1 and site.calls == 0
    content_hash = next(line.rsplit(" ", 1)[-1] for line in preflight.stdout.splitlines()
                        if line.startswith("[site] production build content: "))
    site.env["FAKE_CONTENT"] = "changed after preflight"
    deploy = site.run("--deploy-staged", content_hash)
    assert deploy.returncode == 0 and site.builds == 1 and site.calls == 1


def test_deploy_staged_refuses_content_changed_after_preflight(tmp_path):
    site = Site(tmp_path)
    preflight = site.run("--preflight")
    content_hash = next(line.rsplit(" ", 1)[-1] for line in preflight.stdout.splitlines()
                        if line.startswith("[site] production build content: "))
    staged = site.clone / ".vercel/publication" / content_hash / ".vercel/output/static/index.html"
    staged.write_text("changed after preflight")
    deploy = site.run("--deploy-staged", content_hash)
    assert deploy.returncode == 1 and "staged publication does not match its hash" in deploy.stderr
    assert site.calls == 0


def test_unchanged_content_skips_upload_and_changed_private_content_uploads(tmp_path):
    site = Site(tmp_path)
    first = site.run()
    assert first.returncode == 0 and site.calls == 1
    site.env["FAKE_CONTENT"] = "new private-data-derived page"
    second = site.run()
    assert second.returncode == 0 and site.calls == 2 and len(site.deploys) == 2
    third = site.run()
    assert third.returncode == 0 and "unchanged since last deployment" in third.stdout and site.calls == 2


def test_local_build_failure_cannot_upload_or_stamp(tmp_path):
    site = Site(tmp_path, build="fail")
    result = site.run()
    assert result.returncode == 2 and site.calls == 0
    assert not (site.clone / ".vercel/deployed-hash").exists()


def test_deploy_error_does_not_stamp_the_content(tmp_path):
    site = Site(tmp_path, deploy="err")
    result = site.run()
    assert result.returncode == 1 and "upload failed" in result.stderr
    assert site.calls == 2 and not (site.clone / ".vercel/deployed-hash").exists()


def test_failed_created_deployment_counts_toward_quota_and_stops_retry(tmp_path):
    site = Site(tmp_path, deploy="urlerr")
    site.env["SIGMA_DEPLOYS_PER_DAY"] = "1"
    result = site.run()
    assert result.returncode == 1 and "not retrying" in result.stderr
    assert site.calls == 1 and len(site.deploys) == 1
    assert not (site.clone / ".vercel/deployed-hash").exists()


def test_one_retry_succeeds_when_a_failed_upload_used_quota_but_room_remains(tmp_path):
    site = Site(tmp_path, deploy="urlerr-once")
    result = site.run()
    assert result.returncode == 0 and "retrying once" in result.stderr
    assert site.calls == 2 and len(site.deploys) == 2


def test_deploy_quota_counts_only_uploaded_prebuilt_builds(tmp_path):
    site = Site(tmp_path)
    for value in ("one", "two"):
        site.env["FAKE_CONTENT"] = value
        assert site.run().returncode == 0
    site.env["FAKE_CONTENT"] = "three"
    result = site.run()
    assert result.returncode == 1 and "already made today's 2 deployments" in result.stderr
    assert site.calls == 2 and len(site.deploys) == 2


def test_force_deploy_bypasses_the_daily_quota(tmp_path):
    site = Site(tmp_path)
    site.env["SIGMA_DEPLOYS_PER_DAY"] = "0"
    result = site.run("--force")
    assert result.returncode == 0 and site.calls == 1 and len(site.deploys) == 1
