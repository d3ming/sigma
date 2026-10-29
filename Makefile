.PHONY: preview preview-stop preview-logs
# Local preview on http://localhost:8787, rebuilt on change. See scripts/preview.sh.
preview:
	@scripts/preview.sh restart
preview-stop:
	@scripts/preview.sh stop
preview-logs:
	@scripts/preview.sh logs

.PHONY: publish release release-land
publish:
	@deploy/mac/site-deploy.sh $(if $(DRY_RUN),--preflight)

# Release develop to main through one reviewed PR (AGENTS.md); see scripts/release.sh. `make release DRY_RUN=1` pushes and posts nothing.
release:
	@scripts/release.sh $(if $(DRY_RUN),--dry-run)
release-land:
	@scripts/release.sh land
