import mysql.connector
from flask import request, jsonify
from config import MYSQL_CONFIG
from services.git_service import clone_git_repo, pull_git_repo, push_git_repo

def get_db_connection():
    """Returns a connection to your MySQL database."""
    return mysql.connector.connect(
        host=MYSQL_CONFIG["host"],
        port=MYSQL_CONFIG["port"],
        user=MYSQL_CONFIG["user"],
        password=MYSQL_CONFIG["password"],
        database=MYSQL_CONFIG["database"]
    )

def update_git_info(user_id, data):
    """Updates git credentials. Token is stored as plain text."""
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
        cursor.execute("SELECT id FROM users WHERE git_email=%s AND id != %s", (git_email, user_id))
        if cursor.fetchone():
            return jsonify({"error": "git_email already used by another user"}), 400

        # Update the user record with plain text values
        cursor.execute("""
            UPDATE users
            SET git_username=%s, git_email=%s, git_token=%s
            WHERE id=%s
        """, (git_username, git_email, git_token, user_id))
        
        conn.commit()
        return jsonify({"message": "Git info updated successfully (Plain Text)"}), 200

    except mysql.connector.Error as e:
        return jsonify({"error": f"Database error: {str(e)}"}), 500
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

def get_git_info(user_id):
    """Retrieves plain text git info for the user."""
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

# --- Git Automation ---

def clone():
    data = request.json or {}
    user_id = data.get("user_id")
    session_id = data.get("session_id")
    repo_url = data.get("repo_url")
    branch = data.get("branch", "main")
    token = data.get("token")

    if not all([user_id, session_id, repo_url]):
        return jsonify({"message": {"statusCode": 400, "message": "Missing required fields"}}), 400

    result = clone_git_repo(repo_url, user_id, session_id, branch, token)
    return jsonify({"message": result}), result.get("statusCode", 200)

def pull():
    data = request.json or {}
    user_id = data.get("user_id")
    session_id = data.get("session_id")
    result = pull_git_repo(user_id, session_id, data.get("branch", "main"))
    return jsonify({"message": result}), result.get("statusCode", 200)

def push():
    data = request.json or {}
    user_id = data.get("user_id")
    session_id = data.get("session_id")
    result = push_git_repo(user_id, session_id, data.get("message", "Update"))
    return jsonify({"message": result}), result.get("statusCode", 200)