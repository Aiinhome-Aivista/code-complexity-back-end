import os
import re
import json
import uuid
import google as genai
from flask import request
from utils.response import api_response
from models import db, Project, FileAnalysis, Upload
from config import GRAPH_FOLDER, GEMINI_API_KEY, BASE_URL
from services.arango_service import get_graph_from_arango


# Configure AI
if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
    except: pass




def clean_path(path):
    # Standardize separators, but keep structure mostly intact
    return path.replace('\\', '/')


# --- TREE BUILDER ALGORITHM ---
def build_file_tree(files, user_id, session_id):
    tree = []
   
    # Helper to insert a file node into the tree structure
    def insert_node(current_level, path_parts, file_obj):
        part = path_parts[0]
        is_file = len(path_parts) == 1
       
        # Check if node already exists at this level
        existing_node = next((n for n in current_level if n['name'] == part), None)
       
        if is_file:
            # Calculate Risk Label
            risk_label = "safe"
            if file_obj.risk_score >= 80: risk_label = "critical"
            elif file_obj.risk_score >= 50: risk_label = "high"
            elif file_obj.risk_score >= 20: risk_label = "moderate"


            # Parse issues
            issues = []
            try: issues = json.loads(file_obj.issues_json)
            except: pass
           
            # Construct Download/View URL
            # Matches @app.route('/files/<path:filename>') in app.py
            found_at_url = f"{BASE_URL}/uploads/{user_id}/{session_id}/extracted/{file_obj.filename}"


            node = {
                "id": str(file_obj.id),
                "name": part,
                "type": "file",
                "risk": risk_label,
                "path": "/" + clean_path(file_obj.filename),
                "lines": file_obj.lines_of_code,
                # Fields requested by user:
                "file_id": file_obj.id,
                "filename": file_obj.filename,
                "found_at": found_at_url,
                "issues": issues
            }
            current_level.append(node)
        else:
            # It's a folder
            if not existing_node:
                existing_node = {
                    "id": f"folder-{uuid.uuid4().hex[:6]}",
                    "name": part,
                    "type": "folder",
                    "risk": "safe",
                    "path": "/" + "/".join(path_parts[:-1]),
                    "children": []
                }
                current_level.append(existing_node)
           
            # Recurse into the folder
            insert_node(existing_node['children'], path_parts[1:], file_obj)


    # Build Tree
    for f in files:
        # Clean path and remove 'extracted/' prefix for the tree display logic if desired,
        # or keep it. Here we strip 'extracted/' for cleaner display hierarchy
        display_path = clean_path(f.filename).replace('extracted/', '')
       
        parts = display_path.split('/')
        # Handle cases where path might start with / or be empty
        parts = [p for p in parts if p]
       
        if parts:
            insert_node(tree, parts, f)


    # Post-process: Propagate Folder Risks
    def update_folder_risks(nodes):
        max_risk_val = 0
        risk_map = {"safe": 0, "moderate": 1, "high": 2, "critical": 3}
        rev_map = {0: "safe", 1: "moderate", 2: "high", 3: "critical"}
       
        for node in nodes:
            if node['type'] == 'folder':
                child_max = update_folder_risks(node['children'])
                node['risk'] = rev_map.get(child_max, "safe")
                max_risk_val = max(max_risk_val, child_max)
            else:
                max_risk_val = max(max_risk_val, risk_map.get(node.get('risk', 'safe'), 0))
        return max_risk_val


    update_folder_risks(tree)
    return tree


def get_results(project_id):
    files = FileAnalysis.query.filter_by(project_id=project_id).all()
    project = db.session.get(Project, project_id)
    upload = Upload.query.filter_by(project_id=project_id).order_by(Upload.id.desc()).first()


    if not project:
        return api_response("Project not found", None, 404)


    # 1. Build the Recursive Tree with requested metadata
    file_tree = build_file_tree(files, project.user_id, project.session_id)
   
    graph_url = upload.graph_url if upload else None
   
    def safe_load(data):
        if not data: return []
        if isinstance(data, (dict, list)): return data
        try: return json.loads(data)
        except: return []


    insights = safe_load(upload.insights) if upload else []
    relationships = safe_load(upload.relationships) if upload else []


    return api_response("Fetched", {
        # "fileTree": file_tree,
        "graph_url": graph_url,
        "insights": insights,
        "relationships": relationships,
        "codeHealth": upload.codeHealth,
        "endpointHealth": upload.endpointHealth,
    }, 200)


def get_user_projects():
    user_id = request.args.get('user_id')
    if not user_id:
        return api_response("Missing user_id", [], 400)


    projects = Project.query.filter_by(user_id=user_id).order_by(Project.created_at.desc()).all()
   
    data = []
    for p in projects:
        created_date = p.created_at.strftime("%Y-%m-%d %H:%M") if p.created_at else "Unknown"
        data.append({
            "id": p.id,
            "name": p.name,
            "created_at": created_date,
            "session_id": p.session_id,
            "visualization_status": p.visualization_status or "PENDING",
            "code_health_status": p.code_health_status or "PENDING",
            "api_analysis_status": p.api_analysis_status or "PENDING",
            "relationship_status": p.relationship_status or "PENDING",
            "heatmap_status": p.heatmap_status or "PENDING",
            "files_analyzed": p.files_analyzed
        })


    return api_response("Fetched", data, 200)


def delete_project(project_id):
    project = db.session.get(Project, project_id)
    if project:
        db.session.delete(project)
        db.session.commit()
    return api_response("Deleted", None, 200)




