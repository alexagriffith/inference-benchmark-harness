PYTHON ?= python3
CONFIG ?= examples/benchmark.json
RUN ?= /tmp/inference-benchmark-run
AIPERF ?= aiperf

.PHONY: help plan verify smoke sweep resume report test test-integration
help:
	@echo 'plan             Print commands without network requests or writes'
	@echo 'verify           Read endpoint and metrics; send no inference'
	@echo 'smoke            Send one short request'
	@echo 'sweep            Run configured concurrency points sequentially'
	@echo 'resume           Continue a stopped campaign after reviewing its reason'
	@echo 'report           Read saved results'
	@echo 'test             Run contract tests without AIPerf or a cluster'
	@echo 'test-integration Run AIPerf against a local test server; no GPU needed'
	@echo 'Set CONFIG, RUN and AIPERF to select inputs, output and runtime.'
plan:
	$(PYTHON) -m bench plan --config "$(CONFIG)" --run "$(RUN)" --aiperf "$(AIPERF)"
verify:
	$(PYTHON) -m bench verify --config "$(CONFIG)" --aiperf "$(AIPERF)"
smoke:
	$(PYTHON) -m bench run --config "$(CONFIG)" --run "$(RUN)" --aiperf "$(AIPERF)" --smoke --execute
sweep:
	$(PYTHON) -m bench run --config "$(CONFIG)" --run "$(RUN)" --aiperf "$(AIPERF)" --execute
resume:
	$(PYTHON) -m bench run --config "$(CONFIG)" --run "$(RUN)" --aiperf "$(AIPERF)" --resume --execute
report:
	$(PYTHON) -m bench report --run "$(RUN)"
test:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests -p 'test_*.py' -v
test-integration:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tests/integration.py --aiperf "$(AIPERF)"
