.PHONY: all install_requirements download combine validate validate_sources list arcane

PYTHON := $(shell which python3 2>/dev/null || which python)

all: install_requirements download combine validate list arcane

install_requirements:
	$(PYTHON) -m pip install -r lib/requirements.txt

download:
	$(PYTHON) lib/download.py

combine:
	$(PYTHON) lib/combine.py

validate:
	$(PYTHON) lib/validate.py

validate_sources:
	$(PYTHON) lib/validate_sources.py

list:
	$(PYTHON) lib/list.py

arcane:
	$(PYTHON) convert_to_arcane.py

