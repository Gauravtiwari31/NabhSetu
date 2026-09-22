# Nabhsetu. `make demo` takes a cold machine to a served APIx dashboard.
PY ?= python

.PHONY: help install init load-cpi backfill index demo serve test lint coverage report verify reproduce elasticity backtest nowcast status clean

help:
	@echo "make install    install pinned dependencies"
	@echo "make demo       init + backfill + index  (cold machine -> published index)"
	@echo "make serve      dashboard on :8000, API docs at /docs"
	@echo "make test       run the test suite"
	@echo "make coverage   run the suite under coverage"
	@echo "make lint       ruff static analysis"
	@echo "make report     regenerate the PDF test & review report"
	@echo "make verify     hash chain + data-quality contract"
	@echo "make reproduce  recompute every published number and diff"

install:
	$(PY) -m pip install -r requirements.txt

init:
	$(PY) cli.py init

# Optional: the CPI comparator is only needed for `backtest` and `nowcast`.
# Datasets/ is gitignored, so a fresh clone will not have it and `demo` must
# not depend on it.
load-cpi:
	$(PY) cli.py load-cpi --dir $(or $(CPI_DIR),Datasets)

# The window ends 2026-07-31 so the monthly series overlaps the CPI comparator.
# --simulate is REQUIRED here: the synthetic rung ships disabled so it can
# never run in a deployment by accident. Every row it writes is is_synthetic=1.
backfill:
	$(PY) cli.py backfill --simulate --days $(or $(DAYS),240) --end $(or $(END),2026-07-31)

index:
	$(PY) cli.py index

demo: init backfill index status
	@echo ""
	@echo "Ready. Run 'make serve' and open http://127.0.0.1:8000/dashboard/"
	@echo "NOTE: the data is SYNTHETIC. It demonstrates the method, not Indian airfares."

serve:
	$(PY) cli.py serve

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check src tests cli.py --statistics

coverage:
	$(PY) -m coverage run --source=src -m pytest -o addopts="" -q
	$(PY) -m coverage report --precision=1

# Runs the whole review -- tests, coverage, lint, verification, API sweep --
# and renders the test & review report from what it measured.
report:
	$(PY) tools/collect_evidence.py
	$(PY) tools/build_report.py

verify:
	$(PY) cli.py verify

reproduce:
	$(PY) cli.py reproduce

elasticity:
	$(PY) cli.py elasticity

backtest:
	$(PY) cli.py backtest

nowcast:
	$(PY) cli.py nowcast

status:
	$(PY) cli.py status

clean:
	rm -f data/apix.db data/apix.db-wal data/apix.db-shm
