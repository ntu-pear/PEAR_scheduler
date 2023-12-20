# only works for unix because windows is a joke
.PHONY: build clean

build: clean
	python3.10 -m venv env && env/bin/activate && pip install -r requirements.txt

clean:
	rm -rf env
