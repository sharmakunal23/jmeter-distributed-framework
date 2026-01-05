# =============================================================================
# JMeter Distributed Framework - Makefile
# =============================================================================
# Common commands for development and operation
# =============================================================================

.PHONY: help install build test run clean status teardown lint format

# Default target
help:
	@echo "JMeter Distributed Framework"
	@echo ""
	@echo "Setup & Build:"
	@echo "  make install      Install Python dependencies"
	@echo "  make build        Build Docker image"
	@echo "  make build-push   Build and push image to registry"
	@echo ""
	@echo "Local Testing (Docker):"
	@echo "  make run-local    Run test with local Docker workers"
	@echo "  make workers-up   Start Docker workers only"
	@echo "  make workers-down Stop Docker workers"
	@echo "  make logs         View Docker container logs"
	@echo ""
	@echo "AWS Operations:"
	@echo "  make run-aws      Run test on AWS EC2"
	@echo "  make provision    Provision AWS infrastructure only"
	@echo "  make teardown     Tear down all infrastructure"
	@echo "  make status       Show status of infrastructure"
	@echo ""
	@echo "Maintenance:"
	@echo "  make clean        Clean up generated files"
	@echo "  make lint         Run linters"
	@echo "  make format       Format code"
	@echo "  make test         Run tests"

# =============================================================================
# Setup & Build
# =============================================================================

install:
	pip install -r requirements.txt

build:
	cd docker && docker-compose build

build-no-cache:
	cd docker && docker-compose build --no-cache

build-push: build
	python scripts/orchestrator.py build --push

# =============================================================================
# Local Docker Operations
# =============================================================================

# Start workers
workers-up:
	cd docker && docker-compose up -d worker1 worker2

# Start workers (scaled)
workers-up-scaled:
	cd docker && docker-compose --profile scale up -d

# Stop workers
workers-down:
	cd docker && docker-compose down -v

# View logs
logs:
	cd docker && docker-compose logs -f

# Run test locally with 2 workers
run-local: workers-up
	@echo "Waiting for workers to be ready..."
	@sleep 10
	python scripts/orchestrator.py run --mode docker \
		--test-plan test-plans/sample-http-test.jmx \
		--workers 2

# Run test with custom test plan
run-local-custom:
	@if [ -z "$(TEST_PLAN)" ]; then \
		echo "Usage: make run-local-custom TEST_PLAN=path/to/test.jmx"; \
		exit 1; \
	fi
	python scripts/orchestrator.py run --mode docker \
		--test-plan $(TEST_PLAN) \
		--workers $(or $(WORKERS),2)

# =============================================================================
# AWS Operations
# =============================================================================

# Run test on AWS with medium profile
run-aws:
	@if [ -z "$(TEST_PLAN)" ]; then \
		echo "Usage: make run-aws TEST_PLAN=path/to/test.jmx [PROFILE=small|medium|large]"; \
		exit 1; \
	fi
	python scripts/orchestrator.py run --mode aws \
		--test-plan $(TEST_PLAN) \
		--profile $(or $(PROFILE),medium)

# Provision AWS infrastructure only
provision:
	python scripts/orchestrator.py provision --mode aws \
		--profile $(or $(PROFILE),small)

# Show status
status:
	python scripts/orchestrator.py status

# Tear down all infrastructure
teardown:
	python scripts/orchestrator.py teardown --mode all --force

# Tear down AWS only
teardown-aws:
	python scripts/orchestrator.py teardown --mode aws --force

# =============================================================================
# Development
# =============================================================================

lint:
	flake8 scripts/ --max-line-length=120 --ignore=E501
	mypy scripts/ --ignore-missing-imports

format:
	black scripts/ --line-length=120

test:
	pytest tests/ -v --cov=scripts

# =============================================================================
# Cleanup
# =============================================================================

clean:
	# Remove Python cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	
	# Remove results (keep directory)
	rm -rf results/* 2>/dev/null || true
	touch results/.gitkeep
	
	# Remove logs
	rm -rf logs/* 2>/dev/null || true
	
	# Docker cleanup
	cd docker && docker-compose down -v --remove-orphans 2>/dev/null || true

clean-docker:
	docker system prune -f
	docker image prune -f

# =============================================================================
# Monitoring (Optional)
# =============================================================================

monitoring-up:
	cd docker && docker-compose --profile monitoring up -d influxdb grafana

monitoring-down:
	cd docker && docker-compose --profile monitoring down

# =============================================================================
# Quick Shortcuts
# =============================================================================

# Alias for common operations
up: workers-up
down: workers-down
ps: status
