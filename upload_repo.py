import os
import re
import sys
import json
import uuid
import shutil
import zipfile
import argparse
import subprocess
import tempfile
from pathlib import Path

def is_valid_url(url):
    url_pattern = re.compile(
        r'^(?!.*@)'
        r'https?://'  # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?)'  # domain...
        r'(?::\d+)?'  # optional port
        r'(?:/?|[/?][^@\s]+)?$', re.IGNORECASE)
    return re.match(url_pattern, url or "") is not None

def isValidBranchOrCommit(str):
    pattern = r'^(?!.*(?:\.\.|@{|//))[a-zA-Z0-9][a-zA-Z0-9._\-/]*$'
    return re.match(pattern, str or "") is not None

def run_cmd(args, cwd=None):
    try:
        return subprocess.check_output(args, cwd=cwd, stderr=subprocess.STDOUT).decode("utf-8").strip()
    except subprocess.CalledProcessError as e:
        print(f"[!] Error running {' '.join(args)}: {e.output.decode('utf-8')}")
        raise

def upload_repo(repo_url: str, api_url: str, target_commit: str | None = None, branch: str | None = None):
    # Calculate REPO_NAME from REPO_URL
    if not is_valid_url(api_url) or not is_valid_url(repo_url):
        print("Invalid API or Repo Url")
        sys.exit(1)
    repo_name = repo_url.split("/")[-1].replace(".git", "")
    print(f"[*] Repo Name: {repo_name}")
    print(f"[*] API URL:   {api_url}")

    # 1. Resolve Target Commit BEFORE cloning if not provided
    if not target_commit:
        ref_to_resolve = branch if branch else "HEAD"
        if isValidBranchOrCommit(ref_to_resolve):
            print(f"[*] Resolving remote {ref_to_resolve} for {repo_url}...")
            try:
                ls_remote = run_cmd(["git", "ls-remote", "--", repo_url, ref_to_resolve])
                target_commit = ls_remote.split()[0]
            except Exception as e:
                print(f"[!] Error resolving remote branch {ref_to_resolve}: {e}")
                sys.exit(1)
    
    if not isValidBranchOrCommit(target_commit):
        print("Invalid branch or commit string")
        sys.exit(1)
    print(f"[*] Target Commit: {target_commit}")

    # 2. Pre-flight check: Check if job already exists or repo is already indexed
    print(f"[*] Checking server status for {repo_name} at commit {target_commit}...")
    try:
        # Check current repo status
        repo_resp = run_cmd(["curl", "-G", "-s", f"{api_url}/repo/{repo_name}", "--data-urlencode", f"remote_url={repo_url}"])
        repo_info = json.loads(repo_resp)
        if "stats" in repo_info:
            stats = repo_info["stats"]
            if stats.get("last_commit_id") == target_commit:
                print(f"[*] Skipped: Repository {repo_name} is already indexed at commit {target_commit}.")
                return
        
        # Check for existing job
        job_resp = run_cmd(["curl", "-G", "-s", f"{api_url}/job", "--data", f"repo={repo_name}", "--data", f"commit_id={target_commit}", "--data-urlencode", f"remote_url={repo_url}"])
        job_info = json.loads(job_resp)
        if "status" in job_info:
            status = job_info["status"]
            if status in ["pending", "processing", "completed"]:
                print(f"[*] Skipped: An indexing job for commit {target_commit} is already in state '{status}'.")
                return
    except Exception as e:
        # If job check fails (e.g. 404), we continue
        pass

    # 3. Prepare Temp Clone
    tmp_dir = tempfile.mkdtemp(prefix=f"cg_clone_{repo_name}_")
    try:
        print(f"[*] Cloning repository (treeless) to {tmp_dir}...")
        subprocess.check_call(["git", "clone", "--filter=tree:0", "--quiet", repo_url, tmp_dir])
        
        # Branch detection and repo_name update
        repo_name = select_branch_name(repo_name, tmp_dir, target_commit, branch)
        print(f"[*] Resolved Repo Name: {repo_name}")

        # 4. Get last_commit from server to calculate diff
        last_commit = None
        try:
            repo_resp = run_cmd(["curl", "-G", "-s", f"{api_url}/repo/{repo_name}", "--data-urlencode", f"remote_url={repo_url}"])
            repo_info = json.loads(repo_resp)
            if "stats" in repo_info:
                last_commit = repo_info["stats"].get("last_commit_id")
        except:
            pass

        # 5. Calculate Changes
        changes = {"new": [], "modified": [], "deleted": []}
        files_to_package = []

        if not last_commit or last_commit == "null":
            print(f"[*] Fresh index: packaging all tracked files at {target_commit}...")
            run_cmd(["git", "checkout", "--quiet", target_commit], tmp_dir)
            files = run_cmd(["git", "ls-files"], tmp_dir).splitlines()
            changes["new"] = files
            files_to_package = files
        else:
            print(f"[*] Incremental index from server commit: {last_commit}")
            
            # Verify target commit is newer than last commit (requires the clone to check)
            try:
                run_cmd(["git", "merge-base", "--is-ancestor", last_commit, target_commit], tmp_dir)
            except subprocess.CalledProcessError:
                print(f"[!] Error: Server commit ({last_commit}) is NOT an ancestor of Target commit ({target_commit}).")
                sys.exit(1)

            # Get status of changes: A=Added, M=Modified, D=Deleted
            diff_output = run_cmd(["git", "diff", "--name-status", last_commit, target_commit], tmp_dir).splitlines()
            
            if not diff_output:
                print(f"[*] No changes found between {last_commit} and {target_commit}. Exiting.")
                return

            for line in diff_output:
                if not line.strip(): continue
                parts = line.split(None, 1)
                if len(parts) < 2: continue
                status, path = parts
                
                if status.startswith('A'): changes['new'].append(path)
                elif status.startswith('M'): changes['modified'].append(path)
                elif status.startswith('D'): changes['deleted'].append(path)
                elif status.startswith('R'):
                    rename_parts = path.split(None, 1)
                    if len(rename_parts) == 2:
                        changes['deleted'].append(rename_parts[0])
                        changes['new'].append(rename_parts[1])
            
            files_to_package = changes['new'] + changes['modified']
            run_cmd(["git", "checkout", "--quiet", target_commit], tmp_dir)

        # 6. Package
        zip_path = Path(tempfile.gettempdir()) / f"{repo_name}_payload_{uuid.uuid4().hex}.zip"
        print(f"[*] Creating payload: {zip_path}")
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("change_list.json", json.dumps(changes))
            for f in files_to_package:
                abs_f = Path(tmp_dir) / f
                if abs_f.is_file():
                    zf.write(abs_f, arcname=f"repo/{f}")

        # 7. Upload
        print(f"[*] Uploading {zip_path.stat().st_size / 1024 / 1024:.2f} MB payload...")
        try:
            upload_resp = run_cmd([
                "curl", "-s", "-X", "POST",
                "-F", f"commit_id={target_commit}",
                "-F", f"remote_url={repo_url}",
                "-F", f"file=@{zip_path}",
                f"{api_url}/repo/{repo_name}/index"
            ])
            print(f"[+] Server Response: {upload_resp}")
        except Exception as e:
            print(f"[!] Error during upload: {e}")
        finally:
            if zip_path.exists():
                os.remove(zip_path)

    finally:
        print(f"[*] Cleaning up temporary clone...")
        shutil.rmtree(tmp_dir, ignore_errors=True)

def select_branch_name(repo_name, tmp_dir, commit, branch_param=None):
    """Selects the branch name. Returns f'{repo_name}@@{branch}' if not default branch."""
    head = run_cmd(["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], tmp_dir).split("/")[-1]
    branches = [b.strip().split("/")[-1] for b in run_cmd(["git", "branch", "-r", "--contains", commit], tmp_dir).splitlines() if "->" not in b]
    selected = branch_param or (head if head in branches else branches[0] if len(branches) == 1 else None)
    if not selected: print(f"[!] Error: {commit} is on multiple branches: {branches}. Use --branch"); sys.exit(1)
    return f"{repo_name}@@{selected}" if selected != head else repo_name

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Upload repository for indexing')
    parser.add_argument('repo_url', help='Remote URL of the repository')
    parser.add_argument('api_url', help='URL of the Codegraph API')
    parser.add_argument('target_commit', nargs='?', default=None, help='Target commit ID (default: HEAD)')
    parser.add_argument('--branch', default=None, help='Target branch name')
    
    args = parser.parse_args()
    upload_repo(args.repo_url, args.api_url, args.target_commit, args.branch)
