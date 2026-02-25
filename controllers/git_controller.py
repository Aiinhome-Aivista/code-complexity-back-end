import os
import json
import uuid

from flask import request, jsonify
from models import db, User, Project, FileAnalysis, Upload
from utils.response import api_response
from services.ml_service import get_embedding_model
from config import UPLOAD_FOLDER, GRAPH_FOLDER
from services.git_service import (
    clone_git_repo,
    pull_git_repo,
    push_git_repo,
    list_branches,
    checkout_branch,
)
from controllers.visualization_controller import (
    PythonAnalyzer,
    get_chroma_client,
    analyze_file_metrics,
    calculate_code_health,
    generate_internal_insights,
)


# ─────────────────────────────────────────────
# Git Clone / Pull / Push  (simple operations)
# ─────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Clone repo only, return available branches
# POST /api/visualization/upload_git
# Payload: { user_id, project_name, repo_url, token (optional) }
# ─────────────────────────────────────────────────────────────────────────────

def initiate_git_upload():
    """
    Clones the repo using the default branch.
    Returns the session_id and the list of available branches so the 
    client can ask the user which branch to analyse.
    Does NOT start analysis yet.
    """
    data = request.json or {}

    user_id      = data.get("user_id")
    project_name = data.get("project_name")
    repo_url     = data.get("repo_url")
    # token is NOT taken from payload — it is read from the user's DB profile automatically

    # ── Validation ──────────────────────────────────────────────────────────
    user = db.session.get(User, user_id) if user_id else None
    if not user:
        return api_response("User not found", None, 404)

    if not repo_url:
        return api_response("Repository URL required", None, 400)

    # ── Session folders ──────────────────────────────────────────────────────
    session_id     = str(uuid.uuid4())
    session_folder = os.path.join(UPLOAD_FOLDER, str(user_id), session_id)
    graph_folder   = os.path.join(GRAPH_FOLDER,  str(user_id), session_id)
    os.makedirs(session_folder, exist_ok=True)
    os.makedirs(graph_folder,   exist_ok=True)

    # ── Clone (default remote HEAD branch) ───────────────────────────────────
    clone_result = clone_git_repo(
        repo_url=repo_url,
        user_id=user_id,
        session_id=session_id
        # branch & token omitted — service picks up DB token & remote HEAD
    )

    if clone_result.get("statusCode") != 201:
        return api_response("Failed to clone repository", clone_result, 500)

    # ── List available branches ──────────────────────────────────────────────
    branch_result = list_branches(user_id, session_id)
    branches        = branch_result.get("branches", [])
    current_branch  = branch_result.get("current_branch", "main")

    # ── Store project record as PENDING (no analysis yet) ────────────────────
    new_project = Project(
        name=project_name or f"Git_{session_id[:8]}",
        user_id=user.id,
        session_id=session_id,
        code_health_status="PENDING",
        api_analysis_status="PENDING",
        visualization_status="PENDING",
        relationship_status="PENDING"
    )
    db.session.add(new_project)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return api_response(f"Database error: {str(e)}", None, 500)

    return api_response(
        "Repository cloned. Please select a branch to analyse.",
        {
            "session_id":     session_id,
            "project_id":     new_project.id,
            "current_branch": current_branch,
            "branches":       branches
        },
        200
    )


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Switch branch (if needed) then run full analysis
# POST /api/visualization/select_branch
# Payload: { user_id, session_id, project_id, branch }
# ─────────────────────────────────────────────────────────────────────────────

def select_branch_and_analyze():
    """
    1. Verifies the requested branch exists on the remote.
    2. Switches the cloned repo to that branch and pulls latest files.
    3. Runs the full analysis pipeline on the updated files.
    """
    data = request.json or {}

    user_id    = data.get("user_id")
    session_id = data.get("session_id")
    project_id = data.get("project_id")
    branch     = data.get("branch", "main")

    # ── Validation ──────────────────────────────────────────────────────────
    if not all([user_id, session_id, project_id]):
        return api_response("user_id, session_id, and project_id are required", None, 400)

    user = db.session.get(User, user_id) if user_id else None
    if not user:
        return api_response("User not found", None, 404)

    new_project = db.session.get(Project, project_id)
    if not new_project or str(new_project.session_id) != str(session_id):
        return api_response("Project / session mismatch", None, 404)

    extracted_path = os.path.join(UPLOAD_FOLDER, str(user_id), session_id, "extracted")
    if not os.path.exists(extracted_path):
        return api_response("Cloned repository folder not found. Please clone again.", None, 404)

    # ── Branch check & switch ────────────────────────────────────────────────
    checkout_result = checkout_branch(user_id, session_id, branch)

    if checkout_result.get("statusCode") == 404:
        # Branch doesn't exist — tell the client and stop
        return api_response(
            checkout_result["message"],
            {"available_branches": checkout_result.get("available_branches", [])},
            404
        )

    if checkout_result.get("statusCode") != 200:
        return api_response("Failed to switch branch", checkout_result, 500)

    # ── Analysis Pipeline ────────────────────────────────────────────────────
    analyzer       = PythonAnalyzer()
    relationships  = []
    unique_nodes   = set()
    files_data     = []

    embedding_model = get_embedding_model()
    collection = get_chroma_client().get_or_create_collection(
        name=f"session_{session_id}"
    )

    IGNORE_DIRS = {'.git', '__pycache__', 'node_modules', 'venv', 'env'}

    for root, dirs, files in os.walk(extracted_path):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]

        for f in files:
            file_path = os.path.join(root, f)

            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as fr:
                    content = fr.read()
            except Exception:
                continue

            rel_file = os.path.relpath(file_path, extracted_path).replace("\\", "/")
            lines    = len(content.splitlines())

            if f.endswith(".py"):
                analyzer.analyze(file_path, relationships, unique_nodes)
            else:
                unique_nodes.add(rel_file)

            risk    = min(100, int((content.count("if ") + content.count("for ")) * 1.5))
            metrics = analyze_file_metrics(content, lines)
            ext     = os.path.splitext(f)[1].lower()

            files_data.append({
                "id":           rel_file,
                "filename":     rel_file,
                "extension":    ext,
                "folder":       os.path.dirname(rel_file) or "Root",
                "lines_of_code": lines,
                "risk_score":   risk,
                "metrics":      metrics,
                "content":      content
            })

            db.session.add(FileAnalysis(
                project_id=new_project.id,
                filename=rel_file,
                content=content[:5000],
                complexity=risk,
                risk_score=risk,
                lines_of_code=lines,
                security_issues=0,
                issues_json="[]",
                api_json="[]"
            ))
            db.session.commit()

            collection.add(
                documents=[content[:5000]],
                embeddings=[embedding_model.encode(content).tolist()],
                ids=[f"{session_id}_{rel_file}"]
            )

    # ── Finalization ─────────────────────────────────────────────────────────
    analyzed_filenames = [f["filename"] for f in files_data]

    db.session.execute(
        db.text("""
            UPDATE projects
            SET files_analyzed = :files
            WHERE id = :pid
        """),
        {"files": json.dumps(analyzed_filenames), "pid": new_project.id}
    )
    db.session.commit()

    code_health = calculate_code_health(files_data)
    insights    = generate_internal_insights(files_data)

    upload_entry = Upload(
        project_id=new_project.id,
        session_id=session_id,
        codeHealth=code_health,
        files=files_data,
        insights=insights
    )
    db.session.add(upload_entry)
    db.session.commit()

    # Mark statuses as DONE
    for col in ("code_health_status", "api_analysis_status",
                "visualization_status", "relationship_status"):
        db.session.execute(
            db.text(f"UPDATE projects SET {col} = 'DONE' WHERE id = :pid"),
            {"pid": new_project.id}
        )
    db.session.commit()

    return api_response(
        "Git Repository Analysed",
        {
            "project_id": new_project.id,
            "session_id": session_id,
            "branch":     branch
        },
        200
    )