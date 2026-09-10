# Tumbleweed Updater.
#
#   sudo make install      install into PREFIX (default /usr)
#   sudo make uninstall
#   make rpm               build a binary RPM (needs rpm-build)
#   make test              run the test suite
#   make run               run straight from the checkout
#   make lint
#
# install/uninstall just delegate to packaging/install.sh, which is the single
# source of truth for the install layout (the RPM spec calls it too).

PREFIX  ?= /usr
DESTDIR ?=

.PHONY: install uninstall rpm test run lint

install:
	PREFIX=$(PREFIX) DESTDIR=$(DESTDIR) sh packaging/install.sh

uninstall:
	PREFIX=$(PREFIX) DESTDIR=$(DESTDIR) sh packaging/install.sh --uninstall

rpm:
	sh packaging/build-rpm.sh

test:
	python3 -m pytest -q

run:
	python3 -m tumbleweed_updater

lint:
	python3 -m pyflakes tumbleweed_updater helper
