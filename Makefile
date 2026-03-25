CONFIGMAP_NAME ?= upload-repo-script
NAMESPACE      ?= upload-repo
REPO_URL       ?= https://github.com/torvalds/linux
API_URL        ?= https://codegraph.guardops.ai
COMMIT_ID      ?=
IMAGE          ?= cicirello/pyaction:latest
ARGS           := ["$(REPO_URL)","$(API_URL)","$(COMMIT_ID)"]

.PHONY: help local-run docker-run kube-run configmap clean kube-clean

help:
	@echo "Usage: make <target> [REPO_URL=...] [API_URL=...] [COMMIT_ID=...] [NAMESPACE=...]"
	@echo ""
	@echo "Targets:"
	@echo "  local-run   Run script locally using python3"
	@echo "  docker-run  Run script inside a Docker container"
	@echo "  kube-run    Run script as a one-off Pod in Kubernetes (creates namespace & ConfigMap)"
	@echo "  configmap   Generate the upload-repo-configmap.yaml file"
	@echo "  kube-clean  Delete the Kubernetes namespace and all its resources"
	@echo "  clean       Remove local generated files and run kube-clean"

local-run:
	python3 upload_repo.py $(REPO_URL) $(API_URL) $(COMMIT_ID)

docker-run:
	docker run -it --network host --rm -v $(shell pwd):/app -w /app $(IMAGE) python3 upload_repo.py $(REPO_URL) $(API_URL) $(COMMIT_ID)

kube-run: configmap
	@kubectl create namespace $(NAMESPACE) --dry-run=client -o yaml | kubectl apply -f -
	@kubectl apply -f upload-repo-configmap.yaml --namespace=$(NAMESPACE)
	$(eval POD_NAME := upload-repo-$(shell date +%s))
	kubectl run $(POD_NAME) -i --rm --image=$(IMAGE) --namespace=$(NAMESPACE) --restart=Never --overrides='{"spec":{"containers":[{"name":"$(POD_NAME)","image":"$(IMAGE)","command":["python3","-u","/s/upload_repo.py"],"args":$(ARGS),"volumeMounts":[{"name":"s","mountPath":"/s"}]}],"volumes":[{"name":"s","configMap":{"name":"$(CONFIGMAP_NAME)"}}]}}'

configmap:
	@kubectl create configmap $(CONFIGMAP_NAME) --from-file=upload_repo.py --namespace=$(NAMESPACE) --dry-run=client -o yaml > upload-repo-configmap.yaml
	@echo "[*] Generated upload-repo-configmap.yaml"

kube-clean:
	kubectl delete namespace $(NAMESPACE) --ignore-not-found

clean: kube-clean
	rm -f upload-repo-configmap.yaml
