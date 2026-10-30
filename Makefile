.PHONY: preview preview-stop preview-logs
# Local preview on http://localhost:8787, rebuilt on change. See scripts/preview.sh.
preview:
	@scripts/preview.sh restart
preview-stop:
	@scripts/preview.sh stop
preview-logs:
	@scripts/preview.sh logs

.PHONY: publish
export APPROVE PREPARE_ONLY
publish:
	@sh scripts/release.sh
