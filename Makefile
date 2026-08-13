# Chakravyuh task runner.
#
# On Windows without GNU make, use the PowerShell equivalent instead:
#     .\run.ps1 setup | data | train | dev | test
# The two are kept in sync deliberately.

.PHONY: setup data train dev dev-backend dev-frontend test clean

setup:
	cd backend && pip install -r requirements.txt
	cd frontend && npm install

data:
	cd backend && python -m app.simulator.generator

train:
	cd backend && python -m app.detect.train

test:
	cd backend && pytest

# Runs both servers. Backend on :8000, frontend on :5173.
dev:
	@echo "Start these in two terminals:"
	@echo "  make dev-backend"
	@echo "  make dev-frontend"

dev-backend:
	cd backend && uvicorn app.main:app --reload --port 8000

dev-frontend:
	cd frontend && npm run dev

clean:
	rm -rf backend/data backend/models