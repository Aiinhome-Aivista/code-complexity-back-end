import os
import uuid
import json
import time
import shutil
from flask import request
from utils.response import api_response
from file_utils import handle_zip_upload
from services.ml_service import get_embedding_model
from analysis import analyze_code, get_ai_fix, ai_scan_code_detailed
from models import AppliedFix, Upload, db, User, Project, FileAnalysis, TokenUsage
from config import UPLOAD_FOLDER, FREE_TIER_LIMIT_FILES, BASE_URL, MODEL_NAME, MISTRAL_MODEL, UPLOAD_BASE_URL


embedding_model = get_embedding_model()


def robust_rmtree(path):
    if not os.path.exists(path): return
    for i in range(5):
        try:
            shutil.rmtree(path)
            return
        except OSError:
            time.sleep(0.2)
    shutil.rmtree(path, ignore_errors=True)


# --- HELPER: LOG TOKENS ---
def log_token_usage(user_id, session_id, usage_data):
    if not usage_data: return
   
    try:
        provider = usage_data.get("provider", "unknown")
        input_tok = usage_data.get("input", 0)
        output_tok = usage_data.get("output", 0)
       
        # Basic Cost Estimation (Approximate)
        cost = 0.0
        if provider == "gemini":
            # ~$0.075 / 1M input, $0.30 / 1M output
            cost = (input_tok / 1_000_000 * 0.075) + (output_tok / 1_000_000 * 0.30)
            model = MODEL_NAME
        elif "mistral" in provider:
            # ~$0.25 / 1M input
            cost = (input_tok / 1_000_000 * 0.25) + (output_tok / 1_000_000 * 0.50)
            model = MISTRAL_MODEL
        else:
            model = "unknown"


        record = TokenUsage(
            user_id=user_id,
            session_id=session_id,
            provider=provider,
            model_name=model,
            input_tokens=input_tok,
            output_tokens=output_tok,
            total_tokens=input_tok + output_tok,
            estimated_cost=cost
        )
        db.session.add(record)
        db.session.commit()
    except Exception as e:
        print(f"⚠️ Failed to log tokens: {e}")


# --- TREE BUILDER (Sequential IDs: 1, 1-1...) ---
def build_analysis_tree(flat_report, user_id, session_id):
    tree = []
   
    def insert_node(current_level, path_parts, item, parent_id_str, parent_path_str):
        part = path_parts[0]
        is_file = len(path_parts) == 1
       
        existing_node = next((n for n in current_level if n['name'] == part), None)
       
        if existing_node:
            target_node = existing_node
        else:
            idx = len(current_level) + 1
            new_id = f"{parent_id_str}-{idx}" if parent_id_str else str(idx)
            new_path = f"{parent_path_str}/{part}" if parent_path_str else f"/{part}"


            if is_file:
                # Risk Calculation
                risk = "safe"
                if any(i.get('severity') == 'High' for i in item['issues']): risk = "critical"
                elif any(i.get('severity') == 'Medium' for i in item['issues']): risk = "moderate"
                elif len(item['issues']) > 0: risk = "low"
               
                web_safe_path = item['filename'].replace('\\', '/')
                found_at_url = f"{BASE_URL}/uploads/{user_id}/{session_id}/extracted/{web_safe_path}"


                target_node = {
                    "id": new_id,
                    "name": part,
                    "type": "file",
                    "risk": risk,
                    "path": new_path,
                    "lines": item.get('lines', 0),
                    "file_id": item['file_id'],
                    "filename": item['filename'],
                    "found_at": found_at_url,
                    "issues": item['issues']
                }
            else:
                target_node = {
                    "id": new_id,
                    "name": part,
                    "type": "folder",
                    "risk": "safe",
                    "path": new_path,
                    "children": []
                }
            current_level.append(target_node)


        if not is_file:
            insert_node(target_node['children'], path_parts[1:], item, target_node['id'], target_node['path'])


    for item in flat_report:
        clean_path = item['filename'].replace('\\', '/').replace('extracted/', '')
        parts = clean_path.split('/')
        parts = [p for p in parts if p]
        if parts: insert_node(tree, parts, item, "", "")


    # Risk Propagation
    def update_risk(nodes):
        max_risk_val = 0
        risk_map = {"safe": 0, "low": 1, "moderate": 2, "high": 3, "critical": 4}
        rev_map = {0: "safe", 1: "low", 2: "moderate", 3: "high", 4: "critical"}
       
        for node in nodes:
            if node['type'] == 'folder':
                child_risk = update_risk(node['children'])
                node['risk'] = rev_map.get(child_risk, "safe")
                max_risk_val = max(max_risk_val, child_risk)
            else:
                current_val = risk_map.get(node.get('risk', 'safe'), 0)
                max_risk_val = max(max_risk_val, current_val)
        return max_risk_val


    update_risk(tree)
    return tree

def analyze_project_ai():
    data = request.json
    user_id = data.get('user_id')
    session_id = data.get('session_id')

    if not user_id or not session_id:
        return api_response("Missing user_id or session_id", None, 400)

    project = Project.query.filter_by(user_id=user_id, session_id=session_id).first()
    if not project:
        return api_response("Project not found", None, 404)

    # LOCAL filesystem path (for backend, git, os)
    project_folder_path = os.path.join(
        UPLOAD_FOLDER,
        str(user_id),
        session_id,
        "extracted"
    )

    # PUBLIC URL (only for frontend response)
    project_folder_url = f"{UPLOAD_BASE_URL}/{user_id}/{session_id}/extracted"





    # --- NEW LOGIC: CHECK FOR EXISTING DATA (CACHE BYPASS) ---
    # 1. Find the upload record first
    existing_upload = Upload.query.filter_by(project_id=project.id, session_id=session_id).first()
    
    # 2. If data exists, return it immediately and skip the rest
    if existing_upload and existing_upload.analyze_data:
        print(f"🚀 Cache Hit: Returning existing analysis for Session {session_id}")
        
        # If your DB column is JSON type, SQLAlchemy returns a Python list/dict automatically.
        # If it's Text/String, you might need: existing_data = json.loads(existing_upload.analyze_data)
        existing_data = existing_upload.analyze_data
        
        # Calculate a rough count of files if possible, or just default to N/A
        file_count = len(existing_data) if isinstance(existing_data, list) else 0

        return api_response("Analysis Fetched from Cache", {
            "project_id": project.id,
            "project_folder": project_folder_url,
            "files_analyzed": file_count, 
            "FileNode": existing_data
        }, 200)
    # ---------------------------------------------------------

    # If no data found, proceed with standard analysis...
    files = FileAnalysis.query.filter_by(project_id=project.id).all()
   
    flat_report = []
    session_root = os.path.join(UPLOAD_FOLDER, str(user_id), session_id)
   
    # IGNORE FILTER
    IGNORE_DIRS = ['__pycache__', '.git', 'node_modules', 'venv', 'env']
    IGNORE_EXTS = ('.pyc', '.pyo', '.pyd', '.so', '.dll', '.exe', '.jpg', '.png', '.zip')

    for file_record in files:
        if any(bad in file_record.filename for bad in IGNORE_DIRS): continue
        if file_record.filename.endswith(IGNORE_EXTS): continue

        file_path = os.path.join(session_root, file_record.filename)
       
        # Robust Find
        if not os.path.exists(file_path):
            alt_path = os.path.join(session_root, "extracted", file_record.filename)
            if os.path.exists(alt_path): file_path = alt_path
            else:
                for root, _, fs in os.walk(session_root):
                    if os.path.basename(file_record.filename) in fs:
                        file_path = os.path.join(root, os.path.basename(file_record.filename))
                        break
       
        if os.path.exists(file_path):
            try:
                # Calculate Relative Path
                extracted_root = os.path.join(session_root, "extracted")
                
                if os.path.exists(extracted_root) and extracted_root in os.path.abspath(file_path):
                    display_filename = os.path.relpath(file_path, extracted_root)
                else:
                    display_filename = os.path.basename(file_path)
                
                display_filename = display_filename.replace('\\', '/')

                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
               
                if len(content) > 40000: continue

                print(f"AI Analyzing: {display_filename}...")
               
                # CALL AI
                ai_issues, usage = ai_scan_code_detailed(content, display_filename)
               
                if usage:
                    log_token_usage(user_id, session_id, usage)

                if not isinstance(ai_issues, list): ai_issues = []

                # Update File Record
                file_record.issues_json = json.dumps(ai_issues)
                db.session.commit()

                flat_report.append({
                    "file_id": file_record.id,
                    "filename": display_filename,
                    "lines": file_record.lines_of_code,
                    "issues": ai_issues
                })
            except Exception as e:
                print(f"Failed to analyze {file_record.filename}: {e}")
                continue

    project_tree = build_analysis_tree(flat_report, user_id, session_id)

    # Save to Database (Reuse the 'existing_upload' variable if it was found but empty, or query again)
    if existing_upload:
        existing_upload.analyze_data = project_tree
        db.session.add(existing_upload)
        db.session.commit()
        print("Successfully saved analysis tree to database.")
    else:
        # Fallback if variable was None (unlikely if project exists, but safe to check)
        upload = Upload.query.filter_by(project_id=project.id, session_id=session_id).first()
        if upload:
            upload.analyze_data = project_tree
            db.session.add(upload)
            db.session.commit()

    return api_response("Full Project Analysis Complete", {
        "project_id": project.id,
        "project_folder": project_folder_url,
        "files_analyzed": len(flat_report),
        "FileNode": project_tree
    }, 200)


# --- 1. GENERATE AI FIX SUGGESTION ---
def generate_ai_suggestion():
    data = request.json
    snippet = data.get('snippet')
    error = data.get('error')
    filename = data.get('filename', 'code')
    user_id = data.get('user_id') 

    if not snippet or not error:
        return api_response("Missing code snippet or error details", None, 400)

    try:
        # Call your existing AI service
        suggestion_json, usage = get_ai_fix(snippet, error, filename)
        
        # Log tokens if user_id is present
        if user_id and usage:
            log_token_usage(user_id, "ai-fix", usage)

        return api_response("AI Fix Generated", {"suggestion": suggestion_json}, 200)
    except Exception as e:
        print(f"Error generating fix: {e}")
        return api_response("Failed to generate fix", str(e), 500)


# --- 2. SAVE FILE TO SERVER ---
def save_file():
    data = request.json
    user_id = data.get('user_id')
    session_id = data.get('session_id')
    filename = data.get('filename') # e.g. "controllers/auth_controller.py"
    new_content = data.get('content')

    if not all([user_id, session_id, filename, new_content]):
        return api_response("Missing required fields", None, 400)

    # 1. Construct the path securely
    # We assume files are in the 'extracted' folder based on your previous structure
    session_root = os.path.join(UPLOAD_FOLDER, str(user_id), session_id)
    target_path = os.path.join(session_root, "extracted", filename)

    # 2. Security Check (Prevent Directory Traversal)
    # Ensure the target path is actually inside the user's session folder
    if not os.path.abspath(target_path).startswith(os.path.abspath(session_root)):
        return api_response("Invalid file path", None, 403)

    try:
        # 3. Write the new content to the file
        with open(target_path, 'w', encoding='utf-8') as f:
            f.write(new_content)

        # 4. OPTIONAL: Update the database record to mark it as "modified"
        # This helps if you want to show a "Fixed" status in the UI later
        file_record = FileAnalysis.query.filter_by(
             filename=filename 
             # You might need to join with Project to filter by session_id effectively here
        ).first()
        
        return api_response("File Saved Successfully", {"path": filename}, 200)

    except Exception as e:
        print(f"Failed to save file: {e}")
        return api_response("Failed to save file", str(e), 500)


# Pass-through functions for other endpoints managed elsewhere
def analyze_upload(): pass
# def save_file(): pass
def analyze_file_issues(): pass



def apply_ai_fix():
    data = request.json

    user_id = data.get("user_id")
    session_id = data.get("session_id")
    filename = data.get("filename")
    original_snippet = data.get("original_snippet")
    suggested_fix = data.get("suggested_fix")

    if not all([user_id, session_id, filename, original_snippet, suggested_fix]):
        return api_response("Missing required fields", None, 400)

    session_root = os.path.join(UPLOAD_FOLDER, str(user_id), session_id)
    file_path = os.path.join(session_root, "extracted", filename)

    if not os.path.abspath(file_path).startswith(os.path.abspath(session_root)):
        return api_response("Invalid file path", None, 403)

    if not os.path.exists(file_path):
        return api_response("File not found", None, 404)

    try:
        # -----------------------------
        # 1. APPLY FIX TO FILE
        # -----------------------------
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        if original_snippet not in content:
            return api_response(
                "Original code snippet not found in file",
                None,
                409
            )

        updated_content = content.replace(original_snippet, suggested_fix, 1)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(updated_content)

        # -----------------------------
        # 2. UPDATE FileAnalysis.issues_json
        # -----------------------------
        updated_issues = []  #  initialize first

        project = Project.query.filter_by(
            user_id=user_id,
            session_id=session_id
        ).first()

        if project:
            file_record = FileAnalysis.query.filter_by(
                project_id=project.id,
                filename=filename
            ).first()

            if file_record:
                issues = json.loads(file_record.issues_json or "[]")

                updated_issues = [
                    issue for issue in issues
                    if issue.get("original_snippet") != original_snippet
                ]

                file_record.issues_json = json.dumps(updated_issues)
                db.session.commit()



        # -----------------------------
        # 3. OPTIONAL: TRACK APPLIED FIX
        # -----------------------------
        applied_fix = AppliedFix(
            user_id=user_id,
            session_id=session_id,
            modified_code={
                "filename": filename,
                "code": updated_content
            }
        )
        db.session.add(applied_fix)
        db.session.commit()

        return api_response(
            "AI Fix Applied & Issue Removed",
            {
                "filename": filename,
                "remaining_issues": len(updated_issues),
                "updated_content": updated_content
            },
            200
        )

    except Exception as e:
        print("Apply Fix Error:", e)
        return api_response("Failed to apply fix", str(e), 500)
