import os
from flask_cors import CORS
from extensions import db, mail
from urllib.parse import quote_plus
from flask import Flask, send_from_directory, request, abort
from flask_login import current_user , login_required
from services.subscription_service import upgrade_to_premium 
from config import MYSQL_CONFIG, UPLOAD_FOLDER, GRAPH_FOLDER, Config
# -------------------------------
# Create App
# -------------------------------
app = Flask(__name__)
CORS(app)

# -------------------------------
# Load Config
# -------------------------------
app.config.from_object(Config)

encoded_pass = quote_plus(MYSQL_CONFIG['password'])
app.config['SQLALCHEMY_DATABASE_URI'] = (
    f"mysql+mysqlconnector://{MYSQL_CONFIG['user']}:{encoded_pass}"
    f"@{MYSQL_CONFIG['host']}:{MYSQL_CONFIG['port']}/{MYSQL_CONFIG['database']}"
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# -------------------------------
# Initialize Extensions
# -------------------------------
db.init_app(app)
mail.init_app(app)

# -------------------------------
# Register Models (IMPORTANT)
# -------------------------------
with app.app_context():
    import models
    db.create_all()

# -------------------------------
# NOW Import Controllers (IMPORTANT)
# -------------------------------
from controllers import git_controller
from controllers import auth_controller
from controllers import admin_controller
from controllers import project_controller
from controllers import insight_controller
from controllers import analysis_controller
from controllers import visualization_controller
from controllers.heatmap import code_risk_heatmap
from controllers.analysis_controller import apply_ai_fix
from controllers.download_controller import download_updated_code
from controllers.relationship_controller import get_relationship_flow
from controllers.subscription_controller import get_all_plans, get_plans_by_user

# -------------------------------
# URL Constants
# -------------------------------
AUTH_URL = '/api/auth'
ANALYSIS_URL = '/api'
PROJECT_URL = '/api/projects'
ADMIN_URL = '/api/admin'
INSIGHT_URL = '/api/insights'
VIZ_URL = '/api/visualization'

# -------------------------------
# Ensure Folders Exist
# -------------------------------
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(GRAPH_FOLDER, exist_ok=True)
# --- STATIC FILE SERVING ---
@app.route('/uploads/<user_id>/<session_id>/extracted/<path:filename>')
def serve_extracted_file(user_id, session_id, filename):
    base_dir = os.path.join(UPLOAD_FOLDER, str(user_id), session_id, 'extracted')
    full_path = os.path.join(base_dir, filename)

    # Direct path match
    if os.path.exists(full_path):
        return send_from_directory(os.path.dirname(full_path), os.path.basename(full_path))

    # Search inside extracted folder
    search_filename = os.path.basename(filename)
    for root, dirs, files in os.walk(base_dir):
        if search_filename in files:
            return send_from_directory(root, search_filename)

    # Search session root
    session_root = os.path.join(UPLOAD_FOLDER, str(user_id), session_id)
    possible_path = os.path.join(session_root, search_filename)

    if os.path.exists(possible_path):
        return send_from_directory(session_root, search_filename)

    #  FINAL FALLBACK (VERY IMPORTANT)
    return abort(404, description="File not found")


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

@app.route('/activate/<token>', methods=['GET'])
def activate_account(token):
    return auth_controller.activate_account(token)    

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

@app.route(VIZ_URL + '/upload', methods=['POST'])
def generate_visualization(): 
    return visualization_controller.process_visualization_upload()


@app.route(ANALYSIS_URL + '/analyze_project_ai', methods=['POST'])
def analyze_project_ai(): 
    return analysis_controller.analyze_project_ai()

@app.route(ANALYSIS_URL + "/code_heatmap", methods=["POST"])
def code_risk_heatmap_controller():
    return code_risk_heatmap()

@app.route(ANALYSIS_URL + '/download_updated_code', methods=['GET'])
def download_code_route():
    return download_updated_code()

@app.route(ANALYSIS_URL + "/relationships_flow", methods=["POST"])
def get_relationship_flow_controller():
    return get_relationship_flow()

@app.route(ANALYSIS_URL + "/apply-ai-fix", methods=["POST"])
def apply_fix_route():
    return apply_ai_fix()

# --- GIT & TERMINAL ROUTES ---

@app.route(ANALYSIS_URL + "/clone", methods=["POST"])
def clone():
    return git_controller.clone()

@app.route(ANALYSIS_URL + "/pull", methods=["POST"])
def pull():
    return git_controller.pull()

@app.route(ANALYSIS_URL + "/push", methods=["POST"])
def push():
    return git_controller.push()

@app.route(ANALYSIS_URL + "/terminal", methods=["POST"])
def terminal_route():
    """New REST endpoint for the terminal"""
    return git_controller.terminal_api_handler()

@app.route(ANALYSIS_URL + "/fetch_git_config/<int:user_id>", methods=['GET'])
def api_get_git(user_id):
    return git_controller.get_git_info(user_id)

@app.route(ANALYSIS_URL + "/update_git_config/<int:user_id>", methods=['PUT'])
def api_update_git(user_id):
    data = request.json
    return git_controller.update_git_info(user_id, data)

@app.route(ANALYSIS_URL + "/plans", methods=['GET'])
def api_get_all_plans():
    return get_all_plans()

@app.route(ANALYSIS_URL + "/plans/user/<int:user_id>", methods=['GET'])
def api_get_plans_by_user(user_id):
    return get_plans_by_user(user_id)

@app.route("/upgrade_account", methods=["POST"])
def upgrade():
    data = request.get_json()
    user_id = data.get("user_id") # Get ID from the JSON body
    
    if not user_id:
        return {"error": "User ID is required"}, 400
        
    success, message = upgrade_to_premium(user_id)
    if not success:
        return {"error": message}, 400
        
    return {"message": message}, 200
   

# Git repository upload — Step 1: clone only, return branch list
@app.route(VIZ_URL + '/upload_git', methods=['POST'])
def generate_visualization_from_git():
    return git_controller.initiate_git_upload()

# Git repository upload — Step 2: select branch → analyse
@app.route(VIZ_URL + '/select_branch', methods=['POST'])
def select_branch_and_analyze():
    return git_controller.select_branch_and_analyze()


@app.route(AUTH_URL + '/get-captcha', methods=['GET'])
def get_captcha(): 
    return auth_controller.get_captcha()



if __name__ == "__main__":  
    app.run(host="0.0.0.0", port=3019, debug=True)