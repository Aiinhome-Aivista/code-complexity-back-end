
# import os
# import uuid
# import json
# import time  
# import shutil
# import chromadb
# from flask import request
# from utils.response import api_response
# from file_utils import handle_zip_upload 
# from analysis import analyze_code, get_ai_fix
# from models import db, User, Project, FileAnalysis
# from services.ml_service import get_embedding_model
# from sentence_transformers import SentenceTransformer
# from config import UPLOAD_FOLDER, FREE_TIER_LIMIT_FILES


# embedding_model = get_embedding_model()
# # --- Helper: Robust Delete for Windows ---
# def robust_rmtree(path):
#     """
#     Retries deletion to handle Windows file locks (AntiVirus/Indexing).
#     """
#     if not os.path.exists(path):
#         return
        
#     # Try up to 5 times with small delays
#     for i in range(5):
#         try:
#             shutil.rmtree(path)
#             return # Success
#         except OSError:
#             time.sleep(0.2) # Wait 200ms before retry
            
#     # Final attempt: ignore errors so app doesn't crash
#     shutil.rmtree(path, ignore_errors=True)

# def generate_ai_suggestion():
#     data = request.json
#     snippet = data.get('snippet')
#     error = data.get('error')
#     filename = data.get('filename', 'code')
    
#     if not snippet or not error:
#         return api_response("Missing code snippet or error context", None, 400)

#     suggestion = get_ai_fix(snippet, error, filename)
#     return api_response("AI Suggestion Generated", {"suggestion": suggestion}, 200)

# def analyze_upload():
#     user_id = request.form.get('user_id')
#     if not user_id: return api_response("Unauthorized access", None, 401)
    
#     user = db.session.get(User, user_id)
#     if not user: return api_response("User not found", None, 404)

#     if 'files' not in request.files: return api_response("No files uploaded", None, 400)
#     uploaded_files = request.files.getlist('files')
    
#     session_id = str(uuid.uuid4())
#     session_upload_path = os.path.join(UPLOAD_FOLDER, str(user_id), session_id)
#     os.makedirs(session_upload_path, exist_ok=True)

#     files_to_process = []

#     # --- 1. File Saving Logic ---
#     if len(uploaded_files) == 1 and uploaded_files[0].filename.endswith('.zip'):
#         file = uploaded_files[0]
#         zip_path = os.path.join(session_upload_path, file.filename)
#         file.save(zip_path)
#         extract_path = os.path.join(session_upload_path, "extracted")
#         try:
#             files_to_process = handle_zip_upload(zip_path, extract_path)
#         except Exception as e:
#             return api_response(f"Zip failed: {str(e)}", None, 500)
#     else:
#         for file in uploaded_files:
#             if file.filename == '': continue
#             safe_filename = file.filename.replace("..", "") 
#             file_path = os.path.join(session_upload_path, safe_filename)
#             os.makedirs(os.path.dirname(file_path), exist_ok=True)
#             file.save(file_path)
#             files_to_process.append(file_path)

#     # --- Subscription Check with Robust Delete ---
#     if user.subscription_tier == 'free' and len(files_to_process) > FREE_TIER_LIMIT_FILES:
#         robust_rmtree(session_upload_path) # <--- Fixed Call
#         return api_response(f"Limit Reached: Max {FREE_TIER_LIMIT_FILES} files.", None, 403)

#     # --- 2. DB Project Creation ---
#     new_project = Project(
#         name=f"Session_{session_id[:8]}", 
#         user_id=user.id,
#         session_id=session_id
#     )
#     db.session.add(new_project)
#     db.session.commit()

#     # --- 3. VectorDB Initialization (Session Specific) ---
#     chroma_path = os.path.join("chroma_store", str(user_id), session_id)
#     os.makedirs(chroma_path, exist_ok=True)
    
#     chroma_client = chromadb.PersistentClient(path=chroma_path)
#     collection = chroma_client.get_or_create_collection(name=f"session_{session_id}")

#     # --- 4. Analysis & Vector Insertion ---
#     for f_path in files_to_process:
#         try:
#             with open(f_path, 'r', encoding='utf-8', errors='ignore') as f:
#                 content = f.read()
            
#             display_name = os.path.relpath(f_path, session_upload_path)
            
#             # A. Code Analysis
#             metrics = analyze_code(content, display_name)
            
#             record = FileAnalysis(
#                 project_id=new_project.id,
#                 filename=display_name,
#                 content=content,
#                 complexity=metrics['complexity'],
#                 security_issues=metrics['security_issues'],
#                 risk_score=metrics['risk_score'],
#                 lines_of_code=metrics.get('lines_of_code', 0),
#                 issues_json=metrics['issues'],
#                 api_json=metrics['apis']
#             )
#             db.session.add(record)
#             db.session.flush() # Get ID

#             # B. VectorDB Insertion
#             embedding = embedding_model.encode(content).tolist()
#             collection.add(
#                 documents=[content],
#                 embeddings=[embedding],
#                 metadatas=[{
#                     "filename": display_name,
#                     "complexity": metrics['complexity']
#                 }],
#                 ids=[str(record.id)]
#             )

#         except Exception as e:
#             print(f"Skipping {f_path}: {e}")

#     db.session.commit()
    
#     return api_response("Analysis Complete", {
#         "project_id": new_project.id, 
#         "session_id": session_id,
#         "files_count": len(files_to_process)
#     }, 201)

# def save_file():
#     data = request.json
#     file_id = data.get('file_id')
#     new_content = data.get('content')
    
#     if not file_id or new_content is None:
#         return api_response("Missing data", None, 400)

#     file_record = db.session.get(FileAnalysis, file_id)
#     if not file_record: return api_response("File not found", None, 404)
        
#     project = db.session.get(Project, file_record.project_id)
    
#     if project.session_id:
#         file_path = os.path.join(UPLOAD_FOLDER, str(project.user_id), project.session_id, file_record.filename)
#         try:
#             os.makedirs(os.path.dirname(file_path), exist_ok=True)
#             with open(file_path, 'w', encoding='utf-8') as f:
#                 f.write(new_content)
#         except Exception as e:
#             return api_response(f"Disk Save Failed: {str(e)}", None, 500)

#     metrics = analyze_code(new_content, file_record.filename)

#     file_record.content = new_content
#     file_record.complexity = metrics['complexity']
#     file_record.security_issues = metrics['security_issues']
#     file_record.risk_score = metrics['risk_score']
#     file_record.lines_of_code = metrics.get('lines_of_code', 0)
#     file_record.issues_json = metrics['issues']
#     file_record.api_json = metrics['apis']
    
#     db.session.commit()

#     updated_data = file_record.to_dict()
#     try: updated_data['issues'] = json.loads(updated_data['issues'])
#     except: updated_data['issues'] = []
#     try: updated_data['apis'] = json.loads(updated_data['apis'])
#     except: updated_data['apis'] = []

#     return api_response("File saved and re-analyzed", updated_data, 200)


 




import os
import shutil
import uuid
import json
import time
from flask import request
from models import db, User, Project, FileAnalysis, TokenUsage
# Import updated functions
from analysis import analyze_code, get_ai_fix, ai_scan_code_detailed
from file_utils import handle_zip_upload
from utils.response import api_response
from config import UPLOAD_FOLDER, FREE_TIER_LIMIT_FILES, BASE_URL, MODEL_NAME, MISTRAL_MODEL
from services.ml_service import get_embedding_model


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


# --- ANALYZE PROJECT API ---
# def analyze_project_ai():
#     data = request.json
#     user_id = data.get('user_id')
#     session_id = data.get('session_id')


#     if not user_id or not session_id:
#         return api_response("Missing user_id or session_id", None, 400)


#     project = Project.query.filter_by(user_id=user_id, session_id=session_id).first()
#     if not project:
#         return api_response("Project not found", None, 404)


#     files = FileAnalysis.query.filter_by(project_id=project.id).all()
   
#     flat_report = []
#     session_root = os.path.join(UPLOAD_FOLDER, str(user_id), session_id)
   
#     # IGNORE FILTER
#     IGNORE_DIRS = ['__pycache__', '.git', 'node_modules', 'venv', 'env']
#     IGNORE_EXTS = ('.pyc', '.pyo', '.pyd', '.so', '.dll', '.exe', '.jpg', '.png', '.zip')


#     for file_record in files:
#         if any(bad in file_record.filename for bad in IGNORE_DIRS): continue
#         if file_record.filename.endswith(IGNORE_EXTS): continue


#         file_path = os.path.join(session_root, file_record.filename)
       
#         # Robust Find
#         if not os.path.exists(file_path):
#             alt_path = os.path.join(session_root, "extracted", file_record.filename)
#             if os.path.exists(alt_path): file_path = alt_path
#             else:
#                 for root, _, fs in os.walk(session_root):
#                     if os.path.basename(file_record.filename) in fs:
#                         file_path = os.path.join(root, os.path.basename(file_record.filename))
#                         break
       
#         if os.path.exists(file_path):
#             try:
#                 with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
#                     content = f.read()
               
#                 if len(content) > 40000: continue


#                 print(f"AI Analyzing: {file_record.filename}...")
               
#                 # --- CALL AI & GET USAGE ---
#                 ai_issues, usage = ai_scan_code_detailed(content, file_record.filename)
               
#                 # --- LOG TOKENS ---
#                 if usage:
#                     log_token_usage(user_id, session_id, usage)


#                 if not isinstance(ai_issues, list): ai_issues = []


#                 # Update File Record
#                 file_record.issues_json = json.dumps(ai_issues)
#                 db.session.commit()


#                 flat_report.append({
#                     "file_id": file_record.id,
#                     "filename": file_record.filename,
#                     "lines": file_record.lines_of_code,
#                     "issues": ai_issues
#                 })
#             except Exception as e:
#                 print(f"Failed to analyze {file_record.filename}: {e}")
#                 continue


#     project_tree = build_analysis_tree(flat_report, user_id, session_id)


#     return api_response("Full Project Analysis Complete", {
#         "project_id": project.id,
#         "files_analyzed": len(flat_report),
#         "FileNode": project_tree
#     }, 200)


def analyze_project_ai():
    data = request.json
    user_id = data.get('user_id')
    session_id = data.get('session_id')

    if not user_id or not session_id:
        return api_response("Missing user_id or session_id", None, 400)

    project = Project.query.filter_by(user_id=user_id, session_id=session_id).first()
    if not project:
        return api_response("Project not found", None, 404)

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
                # --- NEW LOGIC START: CALCULATE RELATIVE PATH ---
                # This fixes the "missing subfolder" issue.
                extracted_root = os.path.join(session_root, "extracted")
                
                # Check if the file is inside the 'extracted' folder
                # os.path.abspath ensures we are comparing full paths
                if os.path.exists(extracted_root) and extracted_root in os.path.abspath(file_path):
                    # This turns "C:/.../extracted/controllers/auth.py" into "controllers/auth.py"
                    display_filename = os.path.relpath(file_path, extracted_root)
                else:
                    # Fallback: Just use the filename if it's not in the extracted folder
                    display_filename = os.path.basename(file_path)
                
                # Windows Fix: Ensure forward slashes for web URLs
                display_filename = display_filename.replace('\\', '/')
                # --- NEW LOGIC END ---

                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
               
                if len(content) > 40000: continue

                print(f"AI Analyzing: {display_filename}...")
               
                # --- CALL AI & GET USAGE ---
                # Changed: Pass 'display_filename' instead of 'file_record.filename'
                ai_issues, usage = ai_scan_code_detailed(content, display_filename)
               
                # --- LOG TOKENS ---
                if usage:
                    log_token_usage(user_id, session_id, usage)

                if not isinstance(ai_issues, list): ai_issues = []

                # Update File Record
                file_record.issues_json = json.dumps(ai_issues)
                db.session.commit()

                flat_report.append({
                    "file_id": file_record.id,
                    "filename": display_filename, # <--- CRITICAL UPDATE HERE
                    "lines": file_record.lines_of_code,
                    "issues": ai_issues
                })
            except Exception as e:
                print(f"Failed to analyze {file_record.filename}: {e}")
                continue

    project_tree = build_analysis_tree(flat_report, user_id, session_id)

    return api_response("Full Project Analysis Complete", {
        "project_id": project.id,
        "files_analyzed": len(flat_report),
        "FileNode": project_tree
    }, 200)

def generate_ai_suggestion():
    data = request.json
    snippet = data.get('snippet')
    error = data.get('error')
    filename = data.get('filename', 'code')
    user_id = data.get('user_id', 1) # Default to 1 if missing for now
   
    if not snippet or not error:
        return api_response("Missing code/error", None, 400)
   
    # --- CALL AI FIX & GET USAGE ---
    suggestion_json, usage = get_ai_fix(snippet, error, filename)
   
    if usage:
        # Assuming session_id isn't strictly needed for quick fixes, or pass "adhoc"
        log_token_usage(user_id, "adhoc-fix", usage)


    return api_response("AI Suggestion Generated", {"suggestion": suggestion_json}, 200)


# Pass-through functions for other endpoints managed elsewhere
def analyze_upload(): pass
def save_file(): pass
def analyze_file_issues(): pass



