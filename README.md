# Code Diff Generator

A tool for uploading repositories to the Codegraph API for indexing and analysis.

## Overview

This utility clones a repository, calculates the changes since the last indexed commit, packages the modified files, and uploads them to the Codegraph API server for incremental indexing.

## Usage

```bash
python3 upload_repo.py <repo_url> <api_url> [target_commit]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `repo_url` | Remote URL of the Git repository (e.g., `https://github.com/torvalds/linux`) |
| `api_url` | URL of the Codegraph API server (e.g., `https://codegraph.guardops.ai`) |
| `target_commit` | *(Optional)* Specific commit ID to index. Defaults to HEAD if not provided. |

### Examples

Index the latest commit of the Linux kernel:
```bash
python3 upload_repo.py https://github.com/torvalds/linux https://codegraph.guardops.ai
```

Index a specific commit:
```bash
python3 upload_repo.py https://github.com/torvalds/linux https://codegraph.guardops.ai a1b2c3d4e5f6
```

### Advanced Usage

Update all repositories already known to the server:
```bash
curl -s https://codegraph.guardops.ai/repo | jq -r '.repos[] | select (.remote_url != null) | .remote_url' | xargs -I {} python3 upload_repo.py {} https://codegraph.guardops.ai
```

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
- Git installed and available in PATH
- `curl` installed and available in PATH

## API Endpoints

The tool communicates with the following Codegraph API endpoints:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/repo/{repo_name}` | GET | Get repository status and last indexed commit |
| `/job?repo={repo_name}&commit_id={commit}` | GET | Check if a job exists for the given commit |
| `/repo/{repo_name}/index` | POST | Upload repository files for indexing |

## Payload Format

The uploaded ZIP file contains:
- `change_list.json`: JSON file listing new, modified, and deleted files
- `repo/{filepath}`: File contents for new and modified files

Example `change_list.json`:
```json
{
  "new": ["src/new_file.py"],
  "modified": ["src/updated_file.py"],
  "deleted": ["src/old_file.py"]
}