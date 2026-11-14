.PHONY: install bootstrap quick api web test retrain
install:
	cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
	cd frontend && npm install
bootstrap:      ## full data load + model training (~35 min)
	cd backend && .venv/bin/python -m app.bootstrap
quick:          ## latest race only (~4 min); no in-race model
	cd backend && .venv/bin/python -m app.bootstrap --quick
api:
	cd backend && .venv/bin/uvicorn app.main:app --port 8000
web:
	cd frontend && npm run build && npm run start
test:
	cd backend && .venv/bin/python -m pytest -q tests
	cd frontend && npm run typecheck
retrain:        ## refresh data; retrain only if new races arrived; keep old model if the new one validates worse
	cd backend && .venv/bin/python -m app.retrain
