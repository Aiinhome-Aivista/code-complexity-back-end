import os
import shutil
from git import Repo, GitCommandError
from sqlalchemy import text
from config import engine, UPLOAD_FOLDER

# =====================================================
# HELPERS
# =====================================================

def resolve_repo_path(user_id, session_id):
    """Builds the local directory path for the repository."""
    return os.path.join(UPLOAD_FOLDER, str(user_id), str(session_id), "extracted")

def _get_user_git_credentials(user_id):
    try:
        u_id = int(user_id)
        with engine.connect() as connection:
            query = text("SELECT git_username, git_email, git_token FROM users WHERE id = :uid")
            result = connection.execute(query, {"uid": u_id}).fetchone()
            
            # --- THE PRINT STATEMENTS ---
            print("\n" + "="*40)
            print(f"DATABASE FETCH FOR USER ID: {u_id}")
            if result:
                print(f"Username Found: {result[0]}")
                print(f"Email Found:    {result[1]}")
                print(f"Token Found:    {result[2][:4]}****" if result[2] else "Token: EMPTY")
            else:
                print("RESULT: No user found with this ID in the database.")
            print("="*40 + "\n")
            # ----------------------------

            if result:
                return {
                    "git_username": result[0],
                    "git_email": result[1],
                    "git_token": str(result[2]).strip() if result[2] else None
                }
            return None
    except Exception as e:
        print(f"DATABASE CRITICAL ERROR: {str(e)}")
        return None
    """
    Fetch credentials from 'users' table using positional indexing 
    to prevent mapping errors.
    """
    try:
        u_id = int(user_id)
        with engine.connect() as connection:
            query = text("SELECT git_username, git_email, git_token FROM users WHERE id = :uid")
            result = connection.execute(query, {"uid": u_id}).fetchone()
            
            print(f"--- DB DEBUG: Querying ID {u_id} ---")
            print(f"--- RAW RESULT: {result} ---")

            if result:
                # result[0]=username, result[1]=email, result[2]=token
                username = result[0]
                email = result[1]
                token = result[2]

                if token and str(token).strip():
                    return {
                        "git_username": username or "API_User",
                        "git_email": email or "api@example.com",
                        "git_token": str(token).strip()
                    }
                else:
                    print(f"DEBUG: User {u_id} found, but git_token column is empty.")
            else:
                print(f"DEBUG: No record found in 'users' table for id {u_id}")
            
            return None
    except Exception as e:
        print(f"DATABASE CRITICAL ERROR: {str(e)}")
        return None

def _prepare_authenticated_url(url, token):
    """Injects the token into the HTTPS URL."""
    if not token:
        return url
    clean_url = url.split("@")[-1] if "@" in url else url.replace("https://", "")
    return f"https://{token}@{clean_url}"

def _validate_local_git_path(target_dir):
    """Checks if the local directory is a valid git repo."""
    if not os.path.exists(target_dir):
        return {"statusCode": 404, "status": "error", "message": "Directory not found"}
    if not os.path.exists(os.path.join(target_dir, ".git")):
        return {"statusCode": 400, "status": "error", "message": "Not a Git repository"}
    return None

# =====================================================
# CORE FUNCTIONS (Exported to Controller)
# =====================================================

def clone_git_repo(repo_url, user_id, session_id, branch="main", token=None):
    try:
        target_dir = resolve_repo_path(user_id, session_id)
        if os.path.exists(target_dir):
            shutil.rmtree(target_dir)
        os.makedirs(target_dir, exist_ok=True)

        creds = _get_user_git_credentials(user_id)
        active_token = token or (creds.get('git_token') if creds else None)
        
        auth_url = _prepare_authenticated_url(repo_url, active_token)
        repo = Repo.clone_from(auth_url, target_dir, branch=branch, depth=1)

        if creds:
            with repo.config_writer() as cw:
                cw.set_value("user", "name", creds['git_username'])
                cw.set_value("user", "email", creds['git_email'])

        return {"statusCode": 201, "status": "success", "message": "Cloned and configured"}
    except Exception as e:
        return {"statusCode": 500, "status": "error", "message": f"Clone Error: {str(e)}"}

def pull_git_repo(user_id, session_id, branch="main"):
    try:
        target_dir = resolve_repo_path(user_id, session_id)
        err = _validate_local_git_path(target_dir)
        if err: return err

        creds = _get_user_git_credentials(user_id)
        repo = Repo(target_dir)

        if creds and creds.get('git_token'):
            auth_url = _prepare_authenticated_url(repo.remotes.origin.url, creds['git_token'])
            repo.remotes.origin.set_url(auth_url)

        repo.remotes.origin.pull(branch)
        return {"statusCode": 200, "status": "success", "message": "Pulled successfully"}
    except Exception as e:
        return {"statusCode": 500, "status": "error", "message": f"Pull Error: {str(e)}"}

def push_git_repo(user_id, session_id, commit_message="Update from API"):
    try:
        target_dir = resolve_repo_path(user_id, session_id)
        err = _validate_local_git_path(target_dir)
        if err: return err

        creds = _get_user_git_credentials(user_id)
        if not creds:
            return {
                "statusCode": 401,
                "status": "error",
                "message": "No Git Token found in user profile."
            }

        repo = Repo(target_dir)
        repo.remotes.origin.set_url(_prepare_authenticated_url(repo.remotes.origin.url, creds['git_token']))

        with repo.config_writer() as cw:
            cw.set_value("user", "name", creds['git_username'])
            cw.set_value("user", "email", creds['git_email'])

        repo.git.add(A=True)
        if repo.is_dirty():
            repo.index.commit(commit_message)
            repo.git.push('origin', repo.active_branch.name)
            return {"statusCode": 200, "status": "success", "message": "Pushed successfully"}
        
        return {"statusCode": 200, "status": "success", "message": "No changes to push"}
    except Exception as e:
        return {"statusCode": 500, "status": "error", "message": f"Push Error: {str(e)}"}


def list_branches(user_id, session_id):
    """
    Returns all available remote branches for the cloned repo.
    """
    try:
        target_dir = resolve_repo_path(user_id, session_id)
        err = _validate_local_git_path(target_dir)
        if err:
            return err

        repo = Repo(target_dir)
        branches = [ref.remote_head for ref in repo.remotes.origin.refs
                    if ref.remote_head != "HEAD"]
        return {
            "statusCode": 200,
            "status": "success",
            "branches": branches,
            "current_branch": repo.active_branch.name
        }
    except Exception as e:
        return {"statusCode": 500, "status": "error", "message": f"List Branches Error: {str(e)}"}


def checkout_branch(user_id, session_id, branch):
    """
    Checks whether `branch` exists on origin.
    If yes, switches to it and pulls the latest files.
    Returns a result dict.
    """
    try:
        target_dir = resolve_repo_path(user_id, session_id)
        err = _validate_local_git_path(target_dir)
        if err:
            return err

        repo = Repo(target_dir)

        # Refresh remote refs (re-auth if token available)
        creds = _get_user_git_credentials(user_id)
        if creds and creds.get("git_token"):
            auth_url = _prepare_authenticated_url(repo.remotes.origin.url, creds["git_token"])
            repo.remotes.origin.set_url(auth_url)
        repo.remotes.origin.fetch()

        # Check if branch exists remotely
        remote_branches = [ref.remote_head for ref in repo.remotes.origin.refs
                           if ref.remote_head != "HEAD"]
        if branch not in remote_branches:
            return {
                "statusCode": 404,
                "status": "error",
                "message": f"Branch '{branch}' does not exist in the remote repository.",
                "available_branches": remote_branches
            }

        # Checkout (create local tracking branch if not already present)
        local_branch_names = [b.name for b in repo.branches]
        if branch in local_branch_names:
            repo.git.checkout(branch)
        else:
            repo.git.checkout("-b", branch, f"origin/{branch}")

        # Pull latest
        repo.remotes.origin.pull(branch)

        return {
            "statusCode": 200,
            "status": "success",
            "message": f"Switched to branch '{branch}' and updated files.",
            "branch": branch
        }
    except GitCommandError as e:
        return {"statusCode": 500, "status": "error", "message": f"Git Error: {str(e)}"}
    except Exception as e:
        return {"statusCode": 500, "status": "error", "message": f"Checkout Error: {str(e)}"}