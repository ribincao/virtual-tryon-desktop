VENV  := .venv
PY    := $(VENV)/bin/python
PIP   := $(VENV)/bin/pip
STAMP := $(VENV)/.deps

.DEFAULT_GOAL := run
.PHONY: run camera check deps clean help

## run     Launch the app (sets up the venv on first run)
run: $(STAMP) guard-config
	$(PY) run.py

## camera  Check the webcam without connecting to Decart (free)
camera: $(STAMP)
	@$(PY) -c "import cv2; c=cv2.VideoCapture(0); ok,f=c.read(); \
	print('camera:', 'OK' if ok else 'FAILED', f.shape if ok else ''); c.release()"

## check   Offline smoke test: config, model, frame pipeline (free)
check: $(STAMP) guard-config
	@QT_QPA_PLATFORM=offscreen $(PY) -c "import numpy as np; \
	from app import config as cfg; from app.camera import fit_to; \
	from app.realtime import RealtimeSession; \
	c=cfg.load(); s=RealtimeSession(c.api_key, c.model); m=s.model; \
	print(f'config  {c.model} idle={c.idle_timeout_sec}s cap=\$${c.max_session_cost_usd}'); \
	print(f'model   {m.width}x{m.height} @{m.fps}'); \
	print(f'frames  (720,1280) -> {fit_to(np.zeros((720,1280,3),np.uint8), m.width, m.height).shape}'); \
	print('OK')"

## deps    Reinstall dependencies
deps:
	@rm -f $(STAMP)
	@$(MAKE) --no-print-directory $(STAMP)

## clean   Remove the venv and caches (keeps config.local.toml)
clean:
	rm -rf $(VENV) .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

$(STAMP): requirements.txt
	@test -d $(VENV) || python3 -m venv $(VENV)
	@$(PIP) install -q --upgrade pip
	$(PIP) install -q -r requirements.txt
	@touch $@

# The API key is never created for you — it would end up in a file you might
# commit, and it has to come from your own Decart account.
.PHONY: guard-config
guard-config:
	@test -f config.local.toml || { \
	  echo "config.local.toml not found."; \
	  echo ""; \
	  echo "  cp config.example.toml config.local.toml"; \
	  echo ""; \
	  echo "then add your API key from https://platform.decart.ai"; \
	  echo "(the file is gitignored — do not commit it)"; \
	  exit 1; }

## help    Show this list
help:
	@grep -E '^## ' $(MAKEFILE_LIST) | sed 's/^## /  make /'
