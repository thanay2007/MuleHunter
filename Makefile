# Chakravyuh task runner.
#
# On Windows without GNU make, use the PowerShell equivalent instead:
#     .\run.ps1 setup | data | train | dev | test
# The two are kept in sync deliberately.

.PHONY: setup data train bench all dev demo dev-backend dev-frontend test clean

setup:
	cd backend && pip install -r requirements.txt
	cd frontend && npm install

data:
	cd backend && python -m app.simulator.generator

train:
	cd backend && python -m app.detect.train

# The 200-incident benchmark. Slow (~45 min) and optional -- the console runs
# without it, and the Evaluation tab says so rather than faking numbers.
bench:
	cd backend && python -m app.eval.harness

# Everything the demo needs.
all: data train

test:
	cd backend && pytest

# Runs both servers. Backend on :8000, frontend on :5173.
dev:
	@echo "Start these in two terminals:"
	@echo "  make dev-backend"
	@echo "  make dev-frontend"

# One command for the stage: check artifacts, boot the API, wait until it
# actually answers, boot the frontend, open the browser. Fumbling with two
# terminals in front of judges is a bad way to spend the first thirty seconds.
demo:
	@test -f backend/data/transactions.parquet || { echo "Missing artifacts. Run: make all"; exit 1; }
	@test -f backend/models/gbdt.txt || { echo "Missing models. Run: make train"; exit 1; }
	@cd backend && uvicorn app.main:app --port 8000 & \
	  until curl -sf http://127.0.0.1:8000/api/health >/dev/null; do sleep 1; done; \
	  echo "API ready."; \
	  cd frontend && npm run dev & \
	  sleep 4 && (xdg-open http://localhost:5173 || open http://localhost:5173) ; \
	  wait

dev-backend:
	cd backend && uvicorn app.main:app --reload --port 8000

dev-frontend:
	cd frontend && npm run dev

clean:
	rm -rf backend/data backend/models