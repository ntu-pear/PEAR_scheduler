# only works for unix because windows is a joke
.PHONY: build clean docker/build docker/run deploy/gcp

ARTIFACTORY := localhost:5000/

build: clean
	python3.10 -m venv env && . env/bin/activate && python3 -m pip install -r requirements.txt

clean:
	rm -rf env

docker/build:
	docker build -t pear_schedule .

docker/run:
	docker run --name pear -p 8080:8080 -it pear_schedule:latest

docker/publish:
	docker build -t $(ARTIFACTORY)pear_schedule:latest .
	docker push $(ARTIFACTORY)pear_schedule:latest

# to login: gcp auth login
docker/login:
	docker login -u _json_key --password-stdin https://asia-southeast1-docker.pkg.dev < pear-schedule-f0dcf4838c63.key

gcp/deploy:
	gcloud run deploy --image=$(ARTIFACTORY)pear_schedule:latest --project=pear-schedule
