# Blaster Mac Client
#
# Common targets:
#   make help      Show this help
#   make venv      Create .venv and install dependencies
#   make test      Run unit tests
#   make run       Run the app (creates venv if needed)
#   make install   Install LaunchAgent (run at login)
#   make package   Build a shareable zip in dist/
#   make clean     Remove venv, caches, and dist/

.PHONY: help venv test run install package clean

PYTHON ?= python3
VENV   := .venv
PIP    := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/pytest
ROOT   := $(abspath .)
NAME   := $(notdir $(ROOT))
DIST   := $(ROOT)/dist
ZIP    := $(DIST)/$(NAME).zip

help:
	@echo "Blaster Mac Client"
	@echo ""
	@echo "  make venv      Create .venv and install dependencies"
	@echo "  make test      Run unit tests"
	@echo "  make run       Run the app (creates venv if needed)"
	@echo "  make install   Install LaunchAgent (run at login)"
	@echo "  make package   Build shareable zip → dist/$(NAME).zip"
	@echo "  make clean     Remove venv, caches, and dist/"
	@echo ""
	@echo "  UI (when running): http://127.0.0.1:8765"

venv:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install -r requirements.txt

test: $(VENV)/bin/python
	$(PYTEST) tests/ -v

run:
	chmod +x run.sh
	./run.sh

install:
	chmod +x install.sh run.sh
	./install.sh

# Stage a clean tree, then zip with a top-level blaster-mac-client/ folder
# so recipients can follow QUICKSTART.txt (cd blaster-mac-client && ./run.sh).
package:
	mkdir -p $(DIST)
	rm -rf $(DIST)/.stage $(ZIP)
	mkdir -p $(DIST)/.stage
	rsync -a \
		--exclude '.venv/' \
		--exclude '.git/' \
		--exclude '.github/' \
		--exclude 'dist/' \
		--exclude 'logs/' \
		--exclude '__pycache__/' \
		--exclude '.pytest_cache/' \
		--exclude '.DS_Store' \
		$(ROOT)/ $(DIST)/.stage/$(NAME)/
	cd $(DIST)/.stage && zip -r $(ZIP) $(NAME)
	rm -rf $(DIST)/.stage
	@echo ""
	@echo "Created $(ZIP)"
	@ls -lh $(ZIP)

clean:
	rm -rf $(VENV) dist .pytest_cache
	find . -type d -name '__pycache__' -prune -exec rm -rf {} +

$(VENV)/bin/python:
	$(MAKE) venv
