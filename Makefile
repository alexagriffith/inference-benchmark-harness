PYTHON ?= python3
CONFIG ?= examples/benchmark.json
RUN ?= /tmp/inference-benchmark-run
AIPERF ?= aiperf
CONTAINER_ENGINE ?= docker
IMAGE ?= inference-benchmark-harness:0.1.0
TEST_ARTIFACTS ?= $(CURDIR)/.container-test-results

.PHONY: benchmark help plan plan-smoke verify smoke sweep resume report test test-integration resume-smoke image test-container
help:
	@echo 'plan             Print commands without network requests or writes'
	@echo 'plan-smoke       Preview the one-request smoke and its budget'
	@echo 'verify           Read endpoint and metrics; send no inference'
	@echo 'smoke            Send one short request'
	@echo 'sweep/benchmark  Run configured points and repeats sequentially'
	@echo 'resume           Continue a stopped campaign after reviewing its reason'
	@echo 'resume-smoke     Resume a failed smoke with its original smoke configuration'
	@echo 'report           Read saved results'
	@echo 'test             Run contract tests without AIPerf or a cluster'
	@echo 'test-integration Run AIPerf against a local test server; no GPU needed'
	@echo 'image            Build IMAGE with CONTAINER_ENGINE (default: docker)'
	@echo 'test-container   Test the built image; save fixtures to TEST_ARTIFACTS'
	@echo 'Set CONFIG, RUN and AIPERF to select inputs, output and runtime.'
plan:
	$(PYTHON) -m bench plan --config "$(CONFIG)" --run "$(RUN)" --aiperf "$(AIPERF)"
plan-smoke:
	$(PYTHON) -m bench plan --config "$(CONFIG)" --run "$(RUN)" --aiperf "$(AIPERF)" --smoke
verify:
	$(PYTHON) -m bench verify --config "$(CONFIG)" --aiperf "$(AIPERF)"
smoke:
	$(PYTHON) -m bench run --config "$(CONFIG)" --run "$(RUN)" --aiperf "$(AIPERF)" --smoke --execute
sweep:
	$(PYTHON) -m bench run --config "$(CONFIG)" --run "$(RUN)" --aiperf "$(AIPERF)" --execute
resume:
	$(PYTHON) -m bench run --config "$(CONFIG)" --run "$(RUN)" --aiperf "$(AIPERF)" --resume --execute
resume-smoke:
	$(PYTHON) -m bench run --config "$(CONFIG)" --run "$(RUN)" --aiperf "$(AIPERF)" --smoke --resume --execute
report:
	$(PYTHON) -m bench report --run "$(RUN)"
test:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests -p 'test_*.py' -v
test-integration:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tests/integration.py --aiperf "$(AIPERF)"

benchmark: sweep

image:
	$(CONTAINER_ENGINE) build -f Containerfile -t "$(IMAGE)" .

test-container:
	@mkdir -p "$(TEST_ARTIFACTS)"
	$(CONTAINER_ENGINE) run --rm --read-only --tmpfs /tmp:rw,size=1g \
	  -v "$(CURDIR)/tests:/opt/harness/tests:ro" \
	  -v "$(CURDIR)/examples:/opt/harness/examples:ro" \
	  -v "$(abspath $(TEST_ARTIFACTS)):/results:rw" -e TMPDIR=/results \
	  --entrypoint python "$(IMAGE)" -c 'import os, subprocess, sys; os.access("/results", os.W_OK) or sys.exit("TEST_ARTIFACTS must be writable by container UID 10001; choose an approved writable directory"); subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"], check=True); subprocess.run([sys.executable, "tests/integration.py", "--aiperf", "/opt/venv/bin/aiperf"], check=True)'
