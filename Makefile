.PHONY: setup test clean

# Create venv and install everything needed to run tests
setup: .venv/.installed

.venv/bin/activate:
	python3 -m venv .venv

.venv/.installed: .venv/bin/activate pyproject.toml tests/fixture_app/pyproject.toml
	.venv/bin/pip install -e '.[dev]' -e tests/fixture_app/ -q
	touch .venv/.installed

# Run all tests (sets up first if needed)
test: .venv/.installed
	.venv/bin/pytest tests/

clean:
	rm -rf .venv
