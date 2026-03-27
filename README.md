# Code Diff Generator

A tool for uploading repositories to the Codegraph API for indexing and analysis.

## Overview

This utility clones a repository, calculates the changes since the last indexed commit, packages the modified files, and uploads them to the Codegraph API server for incremental indexing.

## Usage

### Indexing the latest HEAD
This will pull the latest commit from the default branch.
```bash
python3 upload_repo.py https://github.com/vllm-project/vllm https://codegraph.guardops.ai
```

### Indexing a specific branch
This will pull the latest on the branch and create a "branch" index, separate from the default branch.
```bash
python3 upload_repo.py https://github.com/vllm-project/vllm https://codegraph.guardops.ai --branch "v0.18.1"
```

## Makefile Targets

A `Makefile` is provided to simplify running the script in various environments.

### Variables

You can override these variables when running `make`:
- `REPO_URL`: URL of the repository to index.
- `API_URL`: URL of the Codegraph API.
- `IMAGE`: Docker image to use (default: `cicirello/pyaction:latest`).
- `NAMESPACE`: Kubernetes namespace (default: `upload-repo`).

### Container Execution

- `make docker-run`: Runs the script inside a Docker container.
  ```bash
  make docker-run REPO_URL=https://github.com/torvalds/linux
  ```
- `make kube-run`: Packages the script as a ConfigMap and launches a one-off `kubectl run` pod in a dedicated namespace.
  ```bash 
  make kube-run REPO_URL=https://github.com/torvalds/linux API_URL=http://search-api-service.default.svc.cluster.local:8000
  ```

### Utility Targets

- `make configmap`: Only generates the `upload-repo-configmap.yaml` file.
- `make kube-clean`: Deletes the entire Kubernetes namespace and all its resources.
- `make clean`: Removes the local generated YAML file and runs `kube-clean`.

## How It Works

1. **Resolve Target Commit**: If no commit is specified, resolves the remote HEAD.
2. **Pre-flight Check**: Checks if the repository is already indexed at the target commit or if a job is already pending/processing/completed.
3. **Clone Repository**: Creates a treeless clone in a temporary directory.
4. **Calculate Changes**: Verifies the target commit is a descendant of the last indexed commit, then identifies new, modified, and deleted files.
5. **Package Payload**: Creates a ZIP file containing the change list and the modified file contents.
6. **Upload**: Sends the payload to the Codegraph API for indexing.
7. **Cleanup**: Removes the temporary clone directory.

## Features

- **Incremental Indexing**: Only uploads files that have changed since the last indexed commit.
- **Ancestor Verification**: Ensures the target commit is a descendant of the server's current state.
- **Duplicate Prevention**: Skips upload if the target commit is already indexed or if a job is already in progress.
- **Efficient Cloning**: Uses treeless clones to minimize bandwidth and storage.
- **Automatic Cleanup**: Removes temporary files after upload.

## Requirements

- Python 3.10+
- `git` installed and available in PATH
- `curl` installed and available in PATH
