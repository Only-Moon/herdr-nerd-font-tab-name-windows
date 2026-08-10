.PHONY: test lint

test:
	python3 -m unittest discover -s test -v

lint:
	python3 -m compileall -q lib bin/herdr-nerd-font-tab-name
	sh -n bin/startup
