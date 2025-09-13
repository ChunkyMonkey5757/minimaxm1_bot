# Makefile for MiniMaxM1 Bot

.PHONY: dev clean test

# Kill any stale bot process, then start fresh in paper mode
dev:
	@echo ">> Killing old bot instances..."
	-pkill -f src/main.py || true
	@echo ">> Starting MiniMax in paper mode..."
	PAPER_MODE=true python -m src.main

# Clean up Python cache and logs
clean:
	@echo ">> Cleaning project..."
	rm -rf __pycache__ */__pycache__ .pytest_cache
	rm -f data/*.csv

# Run tests (placeholder for later)
test:
	@echo ">> Running tests..."
	pytest || true
