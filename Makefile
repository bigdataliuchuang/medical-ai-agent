.PHONY: test test-unit test-integration eval lint format typecheck run clean help

# ── Variables ─────────────────────────────────────────────────────────────────
PYTHON   ?= python
SRC      := src tests
PORT     ?= 8000

# ── Default target ────────────────────────────────────────────────────────────
help:
	@echo "Medical Data Agent — available targets:"
	@echo ""
	@echo "  make test            Run all tests (unit + integration)"
	@echo "  make test-unit       Run unit tests only"
	@echo "  make test-integration Run integration tests only (requires duckdb)"
	@echo "  make eval            Run evaluation harness against benchmark questions"
	@echo "  make lint            Check code style with ruff"
	@echo "  make format          Auto-format code with ruff"
	@echo "  make typecheck       Run mypy type checks"
	@echo "  make run             Start the FastAPI dev server on :$(PORT)"
	@echo "  make clean           Remove __pycache__ and .pyc files"

# ── Testing ───────────────────────────────────────────────────────────────────
test:
	$(PYTHON) -m pytest tests/ -v --tb=short

test-unit:
	$(PYTHON) -m pytest tests/ -v --tb=short --ignore=tests/integration

test-integration:
	$(PYTHON) -m pytest tests/integration/ -v --tb=short

# ── Evaluation harness ────────────────────────────────────────────────────────
eval:
	$(PYTHON) evaluation/eval_runner.py
	@echo ""
	@echo "Latest report: evaluation/eval_report.md"
	@echo "Archived to:   evaluation/reports/"

# ── Code quality ──────────────────────────────────────────────────────────────
lint:
	$(PYTHON) -m ruff check $(SRC)

format:
	$(PYTHON) -m ruff format $(SRC)

typecheck:
	$(PYTHON) -m mypy src/

# ── Development server ────────────────────────────────────────────────────────
run:
	$(PYTHON) -m uvicorn ai_data_agent.main:app --reload --port $(PORT)

# ── Housekeeping ──────────────────────────────────────────────────────────────
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	find . -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	@echo "Cleaned."
