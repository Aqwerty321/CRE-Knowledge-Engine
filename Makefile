PYTHON ?= 3.12

.PHONY: sync dev-up dev-down run migrate test golden eval-golden import-samples status explain-query replay-query demo-doctor demo-dry-run secret-scan submission-report toolhouse-smoke demo-check recover-demo

sync:
	uv sync --python $(PYTHON)

dev-up:
	docker compose up -d postgres qdrant

dev-down:
	docker compose down

recover-demo:
	bash scripts/recover-demo-stack.sh

run:
	@PORT="$$(awk -F= '/^CRE_PORT=/{print $$2}' .env 2>/dev/null || true)"; \
	uv run uvicorn app.main:app --host 0.0.0.0 --port "$${PORT:-8000}" --reload --no-access-log

migrate:
	uv run alembic upgrade head

test:
	uv run pytest -q

golden:
	uv run pytest -q -m golden

eval-golden:
	uv run cre-cli eval-golden

import-samples:
	uv run cre-cli import-samples

status:
	uv run cre-cli status

explain-query:
	@test -n "$(QUERY_ID)" || (echo "QUERY_ID is required" && exit 1)
	uv run cre-cli explain-query $(QUERY_ID)

replay-query:
	@test -n "$(QUERY_ID)" || (echo "QUERY_ID is required" && exit 1)
	uv run cre-cli replay-query $(QUERY_ID)

demo-doctor:
	uv run cre-cli demo-doctor --skip-public-callback

demo-dry-run:
	uv run cre-cli demo-dry-run --skip-public-callback

secret-scan:
	uv run cre-cli secret-scan

submission-report:
	uv run cre-cli submission-report --skip-public-callback --format markdown --output .runtime/submission-report.md

toolhouse-smoke:
	@if [ -n "$(QUERY)" ]; then \
		uv run cre-cli toolhouse-smoke "$(QUERY)"; \
	else \
		uv run cre-cli toolhouse-smoke; \
	fi

demo-check:
	$(MAKE) test
	uv run cre-cli eval-golden
	uv run cre-cli demo-doctor --skip-public-callback
	uv run cre-cli demo-dry-run --skip-public-callback
	uv run cre-cli secret-scan
	$(MAKE) status
