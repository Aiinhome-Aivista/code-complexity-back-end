import mysql.connector
import subprocess
import shlex
import os
from flask import request, jsonify
from config import MYSQL_CONFIG
from services.git_service import (
    # clone_git_repo, 
    pull_git_repo, 
    push_git_repo, 
    resolve_repo_path
)

# =====================================================
# DATABASE HELPERS
# =====================================================

def get_db_connection():
    """Returns a connection to your MySQL database."""
    return mysql.connector.connect(
        host=MYSQL_CONFIG["host"],
        port=MYSQL_CONFIG["port"],
        user=MYSQL_CONFIG["user"],
        password=MYSQL_CONFIG["password"],
        database=MYSQL_CONFIG["database"]
    )

# =====================================================
# GIT CONFIGURATION MANAGEMENT
# =====================================================

def update_git_info(user_id, data):
    """Updates git credentials in the database."""
    git_username = data.get('git_username')
    git_email = data.get('git_email')
    git_token = data.get('git_token')

    if not all([git_username, git_email, git_token]):
        return jsonify({"error": "git_username, git_email, and git_token are required"}), 400

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Ensure email isn't stolen by another user ID
        # cursor.execute("SELECT id FROM users WHERE git_email=%s AND id != %s", (git_email, user_id))
        # if cursor.fetchone():
        #     return jsonify({"error": "git_email already used by another user"}), 400

        # Update the user record
        cursor.execute("""
            UPDATE users
            SET git_username=%s, git_email=%s, git_token=%s
            WHERE id=%s
        """, (git_username, git_email, git_token, user_id))
        
        conn.commit()
        return jsonify({"message": "Git info updated successfully"}), 200

    except mysql.connector.Error as e:
        return jsonify({"error": f"Database error: {str(e)}"}), 500
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

def get_git_info(user_id):
    """Retrieves git info for the user."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT git_username, git_email, git_token FROM users WHERE id=%s", (user_id,))
        user = cursor.fetchone()
        if user:
            return jsonify(user), 200
        return jsonify({"error": "User not found"}), 404
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

# =====================================================
# GIT AUTOMATION (REST API)
# =====================================================

# def clone():
#     data = request.json or {}
#     user_id = data.get("user_id")
#     session_id = data.get("session_id")
#     repo_url = data.get("repo_url")
#     branch = data.get("branch", "main")
#     token = data.get("token")

#     if not all([user_id, session_id, repo_url]):
#         return jsonify({"message": {"statusCode": 400, "message": "Missing required fields"}}), 400

#     result = clone_git_repo(repo_url, user_id, session_id, branch, token)
#     return jsonify({"message": result}), result.get("statusCode", 200)

def pull():
    data = request.json or {}
    user_id = data.get("user_id")
    session_id = data.get("session_id")
    # New logic: accept branch from payload, default to 'main'
    branch = data.get("branch") if data.get("branch") else "main"

    if not all([user_id, session_id]):
        return jsonify({"message": {"statusCode": 400, "message": "Missing user_id or session_id"}}), 400

    result = pull_git_repo(user_id, session_id, branch)
    return jsonify({"message": result}), result.get("statusCode", 200)

def push():
    data = request.json or {}
    user_id = data.get("user_id")
    session_id = data.get("session_id")
    result = push_git_repo(user_id, session_id, data.get("message", "Update from API"))
    return jsonify({"message": result}), result.get("statusCode", 200)

# =====================================================
# REST-BASED TERMINAL HANDLER
# =====================================================

ALLOWED_COMMANDS = ['git', 'ls', 'pwd', 'clear', 'echo']

def terminal_api_handler():
    """Handles terminal commands via standard HTTP POST (No WebSockets)."""
    data = request.json or {}
    user_id = data.get("user_id")
    session_id = data.get("session_id")
    command = data.get("command", "").strip()
    
    # Resolve local directory path
    repo_path = resolve_repo_path(user_id, session_id)
    
    if not os.path.exists(repo_path):
        return jsonify({"output": "Error: Repository path not found. Please clone first.\r\n"}), 404

    if not command:
        return jsonify({"output": ""}), 200

    try:
        # 1. Parse command into arguments
        args = shlex.split(command)
        if not args:
            return jsonify({"output": ""}), 200
            
        base_cmd = args[0]

        # 2. Security: Whitelist Check
        if base_cmd not in ALLOWED_COMMANDS:
            return jsonify({"output": f"Access Denied: Command '{base_cmd}' is restricted.\r\n"}), 403
        
        # 3. Security: Prevent Directory Traversal
        if ".." in command:
            return jsonify({"output": "Access Denied: Path traversal not allowed.\r\n"}), 403

        # 4. Execute the command
        process = subprocess.run(
            args, 
            cwd=repo_path, 
            capture_output=True, 
            text=True, 
            timeout=15  # Prevents long-hanging commands
        )
        
        # Combine Standard Output and Errors
        result = process.stdout + process.stderr
        
        # Format for Xterm.js (convert newlines to carriage returns)
        formatted_result = result.replace("\n", "\r\n")
        
        return jsonify({"output": formatted_result}), 200

    except subprocess.TimeoutExpired:
        return jsonify({"output": "Error: Command timed out after 15 seconds.\r\n"}), 504
    except Exception as e:
        return jsonify({"output": f"Execution Error: {str(e)}\r\n"}), 500