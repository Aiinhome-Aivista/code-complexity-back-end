
import os
from models import db
from flask_cors import CORS
from urllib.parse import quote_plus
from controllers import auth_controller
from controllers import admin_controller
from controllers import project_controller
from controllers import insight_controller
from controllers import analysis_controller
from flask import Flask, send_from_directory
from controllers import visualization_controller
from controllers.heatmap import code_risk_heatmap
from config import MYSQL_CONFIG, UPLOAD_FOLDER, GRAPH_FOLDER 
from controllers.download_controller import download_updated_code
from controllers.relationship_controller import get_relationship_flow
from controllers.analysis_controller import apply_ai_fix
# from controllers.analysis_controller import get_project_dependencies


app = Flask(__name__)
CORS(app)

# Database Connection
encoded_pass = quote_plus(MYSQL_CONFIG['password'])
app.config['SQLALCHEMY_DATABASE_URI'] = (
    f"mysql+mysqlconnector://{MYSQL_CONFIG['user']}:{encoded_pass}"
    f"@{MYSQL_CONFIG['host']}:{MYSQL_CONFIG['port']}/{MYSQL_CONFIG['database']}"
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Ensure Folders Exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(GRAPH_FOLDER, exist_ok=True) 

db.init_app(app)
with app.app_context():
    db.create_all()

# --- URL CONSTANTS ---
AUTH_URL = '/api/auth'
ANALYSIS_URL = '/api'
PROJECT_URL = '/api/projects'
ADMIN_URL = '/api/admin'
INSIGHT_URL = '/api/insights'
VIZ_URL = '/api/visualization'

# # --- STATIC FILE SERVING ---
# # 1. Serve Uploaded Files
@app.route('/uploads/<user_id>/<session_id>/extracted/<path:filename>')
def serve_extracted_file(user_id, session_id, filename):
    # Base directory for this session's extracted files
    base_dir = os.path.join(UPLOAD_FOLDER, str(user_id), session_id, 'extracted')
    
    # 1. Try exact match (e.g. app.py)
    full_path = os.path.join(base_dir, filename)
    if os.path.exists(full_path):
        return send_from_directory(os.path.dirname(full_path), os.path.basename(full_path))

    # 2. Smart Search: Look inside subfolders (e.g. controllers/auth_controller.py)
    search_filename = os.path.basename(filename)
    for root, dirs, files in os.walk(base_dir):
        if search_filename in files:
            return send_from_directory(root, search_filename)

    # 3. Fallback to session root
    session_root = os.path.join(UPLOAD_FOLDER, str(user_id), session_id)
    if os.path.exists(os.path.join(session_root, search_filename)):
        return send_from_directory(session_root, search_filename)


# 2. Serve Generated Graphs (NEW)
@app.route('/graphs/<path:filename>')
def serve_graph_files(filename):
    return send_from_directory(GRAPH_FOLDER, filename)

# --- ROUTES ---
@app.route(AUTH_URL + '/register', methods=['POST'])
def register(): 
    return auth_controller.register()

@app.route(AUTH_URL + '/login', methods=['POST'])
def login(): 
    return auth_controller.login()

@app.route(ANALYSIS_URL + '/analyze', methods=['POST'])
def analyze_upload(): 
    return analysis_controller.analyze_upload()

@app.route(ANALYSIS_URL + '/ai-fix', methods=['POST'])
def generate_ai_suggestion(): 
    return analysis_controller.generate_ai_suggestion()

@app.route(ANALYSIS_URL + '/save-file', methods=['POST'])
def save_file(): 
    return analysis_controller.save_file()

@app.route(ANALYSIS_URL + '/results/<int:project_id>', methods=['GET'])
def get_results(project_id): 
    return project_controller.get_results(project_id)

@app.route(PROJECT_URL, methods=['GET'])
def get_user_projects(): 
    return project_controller.get_user_projects()

@app.route(PROJECT_URL + '/delete/<int:project_id>', methods=['DELETE'])
def delete_project(project_id): 
    return project_controller.delete_project(project_id)

@app.route(INSIGHT_URL + '/generate', methods=['POST'])
def generate_insights(): 
    return insight_controller.generate_project_insights()

# --- Visualization Pipeline ---
@app.route(VIZ_URL + '/upload', methods=['POST'])
def generate_visualization(): 
    return visualization_controller.process_visualization_upload()

# Git repository upload
@app.route(VIZ_URL + '/upload_git', methods=['POST'])
def generate_visualization_from_git():
    return visualization_controller.process_git_upload()    


@app.route(ANALYSIS_URL + '/analyze_project_ai', methods=['POST'])
def analyze_project_ai(): 
    return analysis_controller.analyze_project_ai()


@app.route(ANALYSIS_URL + "/code_heatmap", methods=["POST"])
def code_risk_heatmap_controller():
    return code_risk_heatmap()



# --- DEPENDENCY GRAPH ROUTE ---
# @app.route(ANALYSIS_URL + '/dependency_graph', methods=['POST'])
# def dependency_graph_route():
#     return get_project_dependencies()

# --- DOWNLOAD ROUTE ---
@app.route(ANALYSIS_URL + '/download_updated_code', methods=['GET'])
def download_code_route():
    return download_updated_code()


@app.route(ANALYSIS_URL + "/relationships_flow", methods=["POST"])
def get_relationship_flow_controller():
    return get_relationship_flow()


@app.route(ANALYSIS_URL + "/apply-ai-fix", methods=["POST"])
def apply_fix_route():
    return apply_ai_fix()





if __name__ == "__main__":  
    app.run(host="0.0.0.0", port=3019, debug=True)








