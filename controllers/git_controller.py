from flask import request, jsonify
from services.git_service import clone_git_repo, pull_git_repo, push_git_repo

def clone():
    data = request.json or {}
    user_id = data.get("user_id")
    session_id = data.get("session_id") 
    repo_url = data.get("repo_url")
    branch = data.get("branch", "main")
    token = data.get("token")

    if not all([user_id, session_id, repo_url]):
        return jsonify({"message": {"statusCode": 400, "status": "error", "message": "user_id, session_id, and repo_url required"}}), 400

    result = clone_git_repo(repo_url, user_id, session_id, branch, token)
    return jsonify({"message": result}), result.get("statusCode", 200)

def pull():
    data = request.json or {}
    user_id = data.get("user_id")
    session_id = data.get("session_id")
    branch = data.get("branch", "main")

    if not all([user_id, session_id]):
        return jsonify({"message": {"statusCode": 400, "status": "error", "message": "Missing user_id or session_id"}}), 400

    result = pull_git_repo(user_id, session_id, branch)
    return jsonify({"message": result}), result.get("statusCode", 200)

def push():
    data = request.json or {}
    user_id = data.get("user_id")
    session_id = data.get("session_id")
    message = data.get("message", "Update from Flask API")

    if not all([user_id, session_id]):
        return jsonify({"message": {"statusCode": 400, "status": "error", "message": "Missing user_id or session_id"}}), 400

    result = push_git_repo(user_id, session_id, message)
    return jsonify({"message": result}), result.get("statusCode", 200)