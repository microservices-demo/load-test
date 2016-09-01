NAME = weaveworksdemos/load-test	
INSTANCE = load-test
GROUP = weaveworksdemos
TAG=$(TRAVIS_COMMIT)

dockertravisbuild: build
	docker build -t $(NAME):$(TAG) .
	docker login -u $(DOCKER_USER) -p $(DOCKER_PASS)
	scripts/push.sh
