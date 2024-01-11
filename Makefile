# only works for unix because windows is a joke
.PHONY: build clean docker/build docker/run deploy/gcp

build: clean
	python3.10 -m venv env && env/bin/activate && pip install -r requirements.txt

clean:
	rm -rf env

docker/build:
	docker build -t pear_schedule .

docker/run:
	docker run --name pear -p 8000:8000 --network=host -it pear_schedule:latest

# TODO: fix credentials
deploy/gcp:
	gcloud run deploy --image=pear:latest
