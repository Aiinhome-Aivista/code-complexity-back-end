import os
import shutil
from git import Repo

def clone_git_repo(repo_url, target_dir, branch="main", token=None):
    if os.path.exists(target_dir):
        shutil.rmtree(target_dir)

    os.makedirs(target_dir, exist_ok=True)

    if token:
        repo_url = repo_url.replace(
            "https://",
            f"https://{token}@"
        )

    Repo.clone_from(
        repo_url,
        target_dir,
        branch=branch,
        depth=1
    )
