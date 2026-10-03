# Tumbleweed Updater.
#
#   sudo make install      install into PREFIX (default /usr)
#   sudo make uninstall
#   make rpm               build a binary RPM (needs rpm-build)
#   make venv              create .venv with pytest and pyflakes
#   make test              run the test suite
#   make run               run straight from the checkout
#   make lint
#
# install/uninstall just delegate to packaging/install.sh, which is the single
# source of truth for the install layout (the RPM spec calls it too).
#
# test, lint and run use .venv when it exists. The system python3 has PySide6
# and pyte but usually not pytest or pyflakes, and `make venv` builds one that
# sees the system packages and adds those two.

PREFIX  ?= /usr
DESTDIR ?=
PYTHON  ?= $(if $(wildcard .venv/bin/python3),.venv/bin/python3,python3)

.PHONY: install uninstall rpm venv test run lint

install:
	PREFIX=$(PREFIX) DESTDIR=$(DESTDIR) sh packaging/install.sh

uninstall:
	PREFIX=$(PREFIX) DESTDIR=$(DESTDIR) sh packaging/install.sh --uninstall

rpm:
	sh packaging/build-rpm.sh

venv:
	[ -d .venv ] || python3 -m venv --system-site-packages .venv
	.venv/bin/pip install --quiet pytest pyflakes

test:
	QT_QPA_PLATFORM=offscreen $(PYTHON) -m pytest -q

run:
	$(PYTHON) -m tumbleweed_updater

lint:
	$(PYTHON) -m pyflakes tumbleweed_updater helper tests
