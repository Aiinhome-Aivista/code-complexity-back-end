import re
import os
import ast
import json
import uuid
import requests
import chromadb
from google import genai
from flask import request
from models import Upload
from utils.response import api_response
from werkzeug.utils import secure_filename
from utils.file_utils import handle_zip_upload
from services.git_service import clone_git_repo
from models import db, User, Project, FileAnalysis
from services.ml_service import get_embedding_model
from services.arango_service import store_graph_data, generate_graph_html
from config import ACTIVE_LLM, BASE_URL, MISTRAL_API_KEY, MISTRAL_API_URL, MISTRAL_MODEL, MISTRAL_TIMEOUT, UPLOAD_FOLDER, GRAPH_FOLDER, GEMINI_API_KEY, MODEL_NAME




FREE_PLAN_LIMIT = 10 * 1024  # 10 KB
PREMIUM_PLAN_LIMIT = 20 * 1024 * 1024  # 20 MB


CHROMA_PATH = os.path.join(os.getcwd(), "chroma_store")
# Lazy load
_chroma_client = None
def get_chroma_client():
    global _chroma_client
    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
    return _chroma_client




client = None
if GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY)


class PythonAnalyzer:
    IGNORE_LIST = {
        'os', 'sys', 'json', 're', 'math', 'datetime', 'time', 'random',
        'uuid', 'base64', 'asyncio', 'tempfile', 'subprocess', 'shutil',
        'typing', 'collections', 'email', 'smtplib', 'werkzeug', 'dotenv',
        'flask', 'flask_cors', 'mysql.connector', 'requests', 'urllib',
        'google', 'googleapiclient', 'docx', 'fitz', 'pickle', 'pandas', 'numpy',
        'sqlalchemy', 'arango', 'chromadb', 'pyvis', 'logging'
    }
















    def analyze(self, file_path, relationships, file_list):
        filename = os.path.basename(file_path)
        file_list.add(filename)




        with open(file_path, "r", encoding="utf-8", errors="ignore") as source:
            try:
                tree = ast.parse(source.read())
            except:
                return
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        target = alias.name.split('.')[0]
                        if target not in self.IGNORE_LIST:
                            relationships.append({"source": filename, "target": alias.name, "type": "dependency"})
                            file_list.add(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    module = node.module if node.module else "unknown"
                    target = module.split('.')[0]
                    if target not in self.IGNORE_LIST:
                        relationships.append({"source": filename, "target": module, "type": "dependency"})
                        file_list.add(module)


def compute_project_baseline(files_data):
    total_lines = sum(f["lines_of_code"] for f in files_data)
    total_files = len(files_data)

    total_functions = sum(f["content"].count("def ") for f in files_data)
    total_classes = sum(f["content"].count("class ") for f in files_data)


    avg_file_size = total_lines / max(1, total_files)
    avg_functions = total_functions / max(1, total_files)

    return {
        "avg_file_size": avg_file_size,
        "avg_functions": avg_functions,
        "total_files": total_files,
        "total_lines": total_lines
    }

# --- REPLACE THIS FUNCTION ---
def generate_internal_insights(files_data):
    try:
        # --- 1. PROJECT-LEVEL SUMMARY ---
        total_files = len(files_data)
        total_loc = sum(f.get('lines_of_code', 0) for f in files_data)


        avg_risk = round(
            sum(f.get('risk_score', 0) for f in files_data) / total_files, 2
        ) if total_files else 0


        summary = f"""
        Project Overview:
        - Total source files: {total_files}
        - Total lines of code: {total_loc}
        - Average risk score: {avg_risk}
        """
        # --- 2. STRONGER ARCHITECTURAL PROMPT ---
        prompt = f"""
        You are a senior software architect performing a high-level technical assessment.
        Analyze the OVERALL SOFTWARE PROJECT using the summary below:
        {summary}


        STRICT RULES:
        - Do NOT mention file names, controllers, services, or modules
        - Do NOT reference LOC explicitly in the insights
        - Speak only about the project as a whole
        - Provide meaningful architectural observations, not generic statements
        - Each insight must be 2–3 lines long and provide real value
        Focus on:
        - Architecture maturity
        - Scalability readiness
        - Maintainability
        - Technical debt
        - Structural risk patterns


        Provide exactly 5 well-written project-level insights.


        Return ONLY raw JSON in this format:
        {{ "insights": ["Insight 1", "Insight 2", "Insight 3", "Insight 4", "Insight 5"] }}
        """


        print(f"🤖 Generating Enhanced Project Insights using: {ACTIVE_LLM}")
        response_text = ""


        # === GEMINI ===
        if ACTIVE_LLM == "gemini":
            if not GEMINI_API_KEY:
                return ["Gemini API Key missing."]
            resp = client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt
            )
            response_text = resp.text


        # === MISTRAL CLOUD ===
        elif ACTIVE_LLM == "mistral_cloud":
            if not MISTRAL_API_KEY:
                return ["Mistral API Key missing."]

            headers = {
                "Authorization": f"Bearer {MISTRAL_API_KEY}",
                "Content-Type": "application/json"
            }

            payload = {
                "model": MISTRAL_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"}
            }

            resp = requests.post(
                "https://api.mistral.ai/v1/chat/completions",
                json=payload,
                headers=headers
            )

            if resp.status_code == 200:
                response_text = resp.json()['choices'][0]['message']['content']
            else:
                return [f"Mistral Error: {resp.status_code}"]

        # === MISTRAL LOCAL ===
        elif ACTIVE_LLM == "mistral_local":
            payload = {
                "model": "mistral",
                "prompt": prompt,
                "stream": False,
                "format": "json"
            }

            try:
                resp = requests.post(
                    MISTRAL_API_URL,
                    json=payload,
                    timeout=MISTRAL_TIMEOUT
                )

                if resp.status_code == 200:
                    response_text = resp.json().get('response', '')
                else:
                    return ["Local AI Error."]
            except Exception:
                return ["Local AI Unreachable."]
        else:
            return ["Invalid AI configuration."]
        # --- CLEAN & PARSE ---
        cleaned_text = response_text.replace("```json", "").replace("```", "").strip()

        if not cleaned_text:
            return ["AI returned empty response."]

        data = json.loads(cleaned_text)

        return data.get("insights", ["No insights generated."])

    except Exception as e:
        print(f"❌ Project Insight Generation Error: {str(e)}")
        return ["AI analysis unavailable."]


def enhance_reason_impact(metric, reason, impact, score):
    level = "strong" if score >= 4 else "moderate" if score >= 2.5 else "weak"

    enhanced_reason = (
        f"{reason} "
        f"This suggests a {level} state for the {metric} aspect of the project, "
        f"reflecting how consistently this concern is addressed across the codebase."
    )

    enhanced_impact = (
        f"{impact} "
        f"If left unaddressed, this may gradually affect maintainability, "
        f"scalability, and long-term development velocity."
    )

    return enhanced_reason, enhanced_impact

# --- NEW FUNCTION START: Paste this AFTER generate_internal_insights ---
def generate_health_explanations(files_data, ratings):
    """
    Generates detailed code health insights (Reason, Suggestion, Impact) using ACTIVE_LLM.
    """
    try:
        # --- 1. PREPARE CONTEXT & PROMPT ---
        total_files = len(files_data)
        total_lines = sum(f.get('lines_of_code', 0) for f in files_data)
       
        # Calculate raw counts & Find Complex Files
        total_functions = 0
        total_classes = 0
        security_keywords_found = []
       
        # Risk Score
        sorted_by_risk = sorted(files_data, key=lambda x: x.get('risk_score', 0), reverse=True)
        top_complex_files = [f"{f['filename']} (Risk: {f['risk_score']})" for f in sorted_by_risk[:5]]


        for f in files_data:
            content = f.get('content', '')
            total_functions += content.count("def ")
            total_classes += content.count("class ")
            if "eval(" in content or "exec(" in content:
                security_keywords_found.append(f['filename'])

        stats_summary = (
            f"Project Stats: {total_files} files, {total_lines} lines. "
            f"Functions: {total_functions}, Classes: {total_classes}. "
            f"Risky files: {', '.join(security_keywords_found) if security_keywords_found else 'None'}. "
            f"Most Complex Files: {', '.join(top_complex_files)}."
        )

        # --- UPDATED PROMPT FOR DETAILED INSIGHTS ---
        prompt = f"""
        Analyze this Python project stats and scores.
       
        CONTEXT: {stats_summary}
        SCORES: {json.dumps(ratings)}

        For EACH metric (modularity, performance, readability, reliability, security, sizeHealth), provide:
        1. reason: A 1-sentence explanation.
        2. suggestion: A specific, actionable recommendation to fix it.
        3. affected_files: List of 1-3 filenames that likely need attention.
        4. impact: Why this matters (1 sentence).

        Return ONLY a raw JSON object with keys:
        "modularity", "performance", "readability", "reliability", "security", "sizeHealth".
       
        JSON Structure Example:
        {{
            "modularity": {{
                "reason": "...",
                "suggestion": "...",
                "affected_files": ["app.py"],
                "impact": "..."
            }}
        }}
        """
        print(f"🤖 Generating insights using: {ACTIVE_LLM}")
        response_text = ""

        # --- 2. LOGIC BASED ON config.ACTIVE_LLM (Same as before) ---
        if ACTIVE_LLM == "gemini":
            if not GEMINI_API_KEY: return {k: {"reason": "Gemini API Key missing"} for k in ratings}
            resp = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt
            )
            response_text = resp.text

        elif ACTIVE_LLM == "mistral_cloud":
            if not MISTRAL_API_KEY: return {k: {"reason": "Mistral API Key missing"} for k in ratings}
            headers = {"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"}
            payload = {
                "model": MISTRAL_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"}
            }
            resp = requests.post("https://api.mistral.ai/v1/chat/completions", json=payload, headers=headers)
            if resp.status_code == 200: response_text = resp.json()['choices'][0]['message']['content']
            else: return {k: {"reason": "AI Error"} for k in ratings}

        elif ACTIVE_LLM == "mistral_local":
            payload = {"model": "mistral", "prompt": prompt, "stream": False, "format": "json"}
            try:
                resp = requests.post(MISTRAL_API_URL, json=payload, timeout=MISTRAL_TIMEOUT)
                if resp.status_code == 200: response_text = resp.json().get('response', '')
                else: return {k: {"reason": "Local AI Error"} for k in ratings}
            except: return {k: {"reason": "Local AI Unreachable"} for k in ratings}

        else:
            return {k: {"reason": "Invalid AI Config"} for k in ratings}

        # --- 3. CLEAN & PARSE JSON ---
        cleaned_text = response_text.replace("```json", "").replace("```", "").strip()
        if not cleaned_text: return {k: {"reason": "Empty AI Response"} for k in ratings}


        parsed_data = json.loads(cleaned_text)
       
        # Safety Check to ensure structure
        final_data = {}
        for k in ratings.keys():
            item = parsed_data.get(k, {})
            if isinstance(item, str): item = {"reason": item}
           
            raw_reason = item.get("reason", "Analysis unavailable.")
            raw_impact = item.get("impact", "Impact analysis pending.")


            enh_reason, enh_impact = enhance_reason_impact(
                metric=k,
                reason=raw_reason,
                impact=raw_impact,
                score=ratings.get(k, 0)
            )


            final_data[k] = {
                "reason": enh_reason,
                "suggestion": item.get("suggestion", "No suggestion available."),
                "affected_files": item.get("affected_files", []),
                "impact": enh_impact
            }
  
        return final_data

    except Exception as e:
        print(f"❌ AI Explanation Critical Error: {str(e)}")
        return {k: {"reason": "Analysis failed."} for k in ratings}


def process_visualization_upload():
    if 'files' not in request.files: return api_response("No files", None, 400)
    user_id = request.form.get('user_id')
    user = db.session.get(User, user_id) if user_id else None
    project_name = request.form.get('project_name')

    if not user: return api_response("User not found", None, 404)
   
    session_id = str(uuid.uuid4())
    rel_path = os.path.join(str(user_id), session_id)
    session_folder = os.path.join(UPLOAD_FOLDER, rel_path)
    graph_folder = os.path.join(GRAPH_FOLDER, rel_path)
   
    os.makedirs(session_folder, exist_ok=True)
    os.makedirs(graph_folder, exist_ok=True)

    uploaded_files = request.files.getlist('files')
    scan_path = session_folder

    # ==============================
    # PLAN BASED FILE SIZE CHECK
    # ==============================

    if user.subscription_tier  == "PREMIUM":
        max_size = PREMIUM_PLAN_LIMIT
    else:
        max_size = FREE_PLAN_LIMIT

    total_size = 0

    for f in uploaded_files:
        f.seek(0, os.SEEK_END)
        file_size = f.tell()
        f.seek(0)

        total_size += file_size

        if file_size > max_size:
            return api_response(
                f"File '{f.filename}' exceeds your plan limit.",
                None,
                400
            )


    if total_size > max_size:
        return api_response(
            "Total upload size exceeds your plan limit.",
            None,
            400
        )

    if len(uploaded_files) == 1 and uploaded_files[0].filename.endswith('.zip'):
        zip_file = uploaded_files[0]
        save_path = os.path.join(session_folder, secure_filename(zip_file.filename))
        zip_file.save(save_path)
        handle_zip_upload(save_path, os.path.join(session_folder, "extracted"))
        scan_path = os.path.join(session_folder, "extracted")
    else:
        for f in uploaded_files:
            if f.filename: f.save(os.path.join(session_folder, secure_filename(f.filename)))

    # FIX 1: Commit Project Immediately
    new_project = Project(
    name=project_name or f"Session_{session_id[:8]}",
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
        return api_response(f"Database Error: {str(e)}", None, 500)

    analyzer = PythonAnalyzer()
    relationships = []
    unique_nodes = set()
    files_data = []
    embedding_model = get_embedding_model()
    collection = get_chroma_client().get_or_create_collection(name=f"session_{session_id}")


    for root, dirs, files in os.walk(scan_path):
        for f in files:
            file_path = os.path.join(root, f)
            filename = os.path.basename(file_path)
           
            # Step A: AST Analysis
            if f.endswith('.py'): analyzer.analyze(file_path, relationships, unique_nodes)
            else: unique_nodes.add(filename)

            # Step B: Metadata & Database
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as fr: content = fr.read()
                lines = len(content.splitlines())
                risk = min(100, int((content.count('if ') + content.count('for ')) * 1.5))
                folder = os.path.relpath(root, scan_path)
                if folder == '.': folder = "Root"

                ext = os.path.splitext(filename)[1].lower()

                files_data.append({
                    "id": filename,
                    "filename": filename,
                    "extension": ext,        
                    "folder": folder,
                    "lines_of_code": lines,
                    "risk_score": risk,
                    "content": content      
                })

                # FIX 2: Commit Each File Individually to keep connection alive
                db.session.add(FileAnalysis(
                    project_id=new_project.id,
                    filename=filename,
                    content=content[:5000],
                    complexity=risk,
                    risk_score=risk,
                    lines_of_code=lines,
                    security_issues=0,
                    issues_json="[]",
                    api_json="[]"
                ))
                db.session.commit() # Commit per file

                # Add to VectorDB
                collection.add(documents=[content[:5000]], embeddings=[embedding_model.encode(content).tolist()], ids=[f"{session_id}_{filename}"])
            except Exception as e:
                print(f"Error processing file {filename}: {e}")
                db.session.rollback() # Rollback only this file, continue loop


    analyzed_filenames = [f["filename"] for f in files_data]
    print("ANALYZED_FILES =", analyzed_filenames)
    print("PROJECT_ID =", new_project.id)
    result = db.session.execute(
        db.text("""
            UPDATE projects
            SET files_analyzed = :files
            WHERE id = :pid
        """),
        {
            "files": json.dumps(analyzed_filenames),
            "pid": new_project.id
        }
    )
    print("ROWS AFFECTED =", result.rowcount)
    db.session.commit()


    if files_data:
        baseline = compute_project_baseline(files_data)


        for f in files_data:
            f["metrics"] = analyze_file_metrics(
                f["content"],
                f["lines_of_code"],
                baseline
            )


        code_health = calculate_code_health(files_data)
    else:
        code_health = None


    # --- MODIFIED: AI Explanation Logic with new structure ---
    if code_health and 'ratings' in code_health:
        print("Generating detailed AI insights...")
       
       
        explanations = generate_health_explanations(files_data, code_health['ratings'])
       
        enhanced_ratings = {}
        for key, score in code_health['ratings'].items():
            # Get the AI data object for this key
            ai_data = explanations.get(key, {})
           
            # Merge score with AI insights
            enhanced_ratings[key] = {
                "score": score,
                "reason": ai_data.get("reason", "Analysis pending."),
                "suggestion": ai_data.get("suggestion", ""),
                "affected_files": ai_data.get("affected_files", []),
                "impact": ai_data.get("impact", "")
            }
       
        code_health['ratings'] = enhanced_ratings


        # --- NEW: Generate Active Warnings ---
    print("Generating Active Warnings...")
    active_warnings = generate_project_warnings(files_data)
   
    if not active_warnings:
        active_warnings = {
            "public_endpoints": {"count": 0, "items": [], "description": "Analysis unavailable"},
            "missing_validation": {"count": 0, "items": [], "description": "Analysis unavailable"},
            "performance_risks": {"count": 0, "items": [], "description": "Analysis unavailable"}
        }
 
    db.session.execute(
    db.text("""
        UPDATE projects
        SET code_health_status = 'DONE'
        WHERE id = :pid
    """),
    {"pid": new_project.id}
    )
    db.session.commit()

    db.session.execute(
    db.text("""
        UPDATE projects
        SET api_analysis_status = 'DONE'
        WHERE id = :pid
    """),
    {"pid": new_project.id}
    )
    db.session.commit()


    # Step C: ArangoDB
    final_nodes = []
    for node_name in unique_nodes:
        meta = next((f for f in files_data if f['filename'] == node_name), None)
        final_nodes.append(meta if meta else {"id": node_name, "filename": node_name, "folder": "External", "risk_score": 0})


    store_graph_data(session_id, final_nodes, relationships)

    db.session.execute(
    db.text("""
        UPDATE projects
        SET relationship_status = 'DONE'
        WHERE id = :pid
    """),
    {"pid": new_project.id}
    )
    db.session.commit()

    # Step D: Insights
    insights = generate_internal_insights(files_data)
    with open(os.path.join(graph_folder, "insights.json"), "w", encoding="utf-8") as f:
        json.dump(insights, f)

    # Step E: Graph HTML
    html_filename = "graph.html"
    generate_graph_html(session_id, os.path.join(graph_folder, html_filename))


    db.session.execute(
    db.text("""
        UPDATE projects
        SET visualization_status = 'DONE'
        WHERE id = :pid
    """),
    {"pid": new_project.id}
    )
    db.session.commit()


    graph_url = f"{BASE_URL}/graphs/{rel_path.replace(os.sep, '/')}/{html_filename}"


    upload_entry = Upload(
        project_id=new_project.id,
        session_id=session_id,
        graph_url=graph_url,
        codeHealth=code_health,
        files=files_data,
        insights=insights,
        # relationships=relationships
    )


    db.session.add(upload_entry)
    db.session.commit()


    return api_response("Upload Successful", {
    "project_id": new_project.id,
    "session_id": session_id,
    # "graph_url": graph_url,
    # "insights": insights,
    # "files": files_data,
    # "relationships": relationships,
    # "codeHealth": code_health,
    # "activeWarnings": active_warnings,
    }, 200)


def analyze_file_metrics(content, lines, baseline):
    functions = content.count("def ")
    classes = content.count("class ")

    # --- Dynamic Modularity ---
    density = (functions + classes * 2) / max(1, lines)
    expected = baseline["avg_functions"] / max(1, baseline["avg_file_size"])
    modularity = (density / max(0.001, expected)) * 3
    modularity = max(1, min(5, modularity))


    # --- Dynamic Reliability ---
    signals = (
        content.count("try") +
        content.count("except") +
        content.count("raise") +
        content.count("assert")
    )
    reliability = (signals / max(1, lines / 50)) * 3
    reliability = max(1, min(5, reliability))


    readability = max(1, min(5, 5 - (lines / baseline["avg_file_size"])))
    security = max(1, 5 - content.count("eval(") - content.count("exec("))
    performance = max(1, 5 - content.count("for ") * 0.25)
    size_health = max(1, 5 - (lines / baseline["avg_file_size"]))

    return {
        "readability": round(readability, 2),
        "modularity": round(modularity, 2),
        "reliability": round(reliability, 2),
        "security": round(security, 2),
        "performance": round(performance, 2),
        "sizeHealth": round(size_health, 2)
    }


def calculate_code_health(files_data):
    totals = {
        "readability": 0,
        "modularity": 0,
        "security": 0,
        "reliability": 0,
        "performance": 0,
        "sizeHealth": 0
    }

    count = len(files_data)
    if count == 0:
        return None

    for f in files_data:
        for k in totals:
            totals[k] += f["metrics"][k]

    ratings = {k: round(v / count, 1) for k, v in totals.items()}


    WEIGHTS = {
        "readability": 0.2,
        "modularity": 0.25,
        "reliability": 0.2,
        "security": 0.15,
        "performance": 0.1,
        "sizeHealth": 0.1
    }


    overall = sum(ratings[k] * WEIGHTS[k] for k in ratings)
    overall = round(overall * 20)

    strengths = [k for k, v in ratings.items() if v >= 4]
    weaknesses = [k for k, v in ratings.items() if v <= 2]


    #  OVERALL SCORE EXPLANATION
    overall_reason = (
    f"The overall score reflects a balanced state of the project. "
    f"Strong results in {', '.join(strengths)} indicate that the code performs well, "
    f"is relatively easy to understand, and follows good security practices. "
    f"However, the score is noticeably reduced due to weaknesses in "
    f"{', '.join(weaknesses)}, which suggest limited modular structure and insufficient "
    f"defensive or error-handling mechanisms. "
    f"Addressing these weaker areas could significantly improve maintainability, "
    f"scalability, and push the overall score into a higher range."
)


    return {
        "overallScore": {
            "score": int(overall),
            "reason": overall_reason
        },
        "ratings": ratings
    }


# --- REPLACE THIS FUNCTION TO DEBUG ---
def generate_project_warnings(files_data):
    """
    Scans the codebase (Any Language) using AI to find warnings.
    """
    try:
        # Supported extensions for AI analysis
        ALLOWED_EXTENSIONS = {'.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.cpp', '.c', '.php', '.go', '.rs', '.rb'}

        relevant_content = ""
        scanned_count = 0


        for f in files_data:
            ext = os.path.splitext(f['filename'])[1].lower()
           
            # Check if file extension is supported
            if ext in ALLOWED_EXTENSIONS:
                # Limit content to avoid token overflow
                content_snippet = f.get('content', '')[:3000]
                relevant_content += f"\n--- FILE: {f['filename']} ---\n{content_snippet}\n"
                scanned_count += 1

        if not relevant_content:
            return None

        # --- UPDATED PROMPT: Generic (Not specific to Python) ---
        prompt = f"""
        You are a generic Code Security & Performance Auditor. Analyze the provided code snippet.
       
        Identify issues in these 3 categories suitable for the code's language:

        1. "public_endpoints": Exposed API routes/controllers without auth.
        2. "missing_validation": Inputs used without validation/sanitization.
        3. "performance_risks": Blocking operations, heavy loops, or inefficient queries.

        CODE CONTEXT:
        {relevant_content}

        Return ONLY a raw JSON object with this EXACT structure:
        {{
            "public_endpoints": {{
                "count": 0,
                "items": [],
                "description": "Short explanation relative to the language detected"
            }},
            "missing_validation": {{
                "count": 0,
                "items": [],
                "description": "Short explanation relative to the language detected"
            }},
            "performance_risks": {{
                "count": 0,
                "items": [],
                "description": "Short explanation relative to the language detected"
            }}
        }}
        """

        print(f"⚠️ Scanning {scanned_count} files for Active Warnings using: {ACTIVE_LLM}")
       
        # --- AI CALL LOGIC (Same as before) ---
        response_text = ""
        if ACTIVE_LLM == "gemini":
            if not GEMINI_API_KEY: return None
            resp = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt
            )
            response_text = resp.text


        elif ACTIVE_LLM == "mistral_cloud":
            if not MISTRAL_API_KEY: return None
            headers = {"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"}
            payload = {
                "model": MISTRAL_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"}
            }
            resp = requests.post("https://api.mistral.ai/v1/chat/completions", json=payload, headers=headers)
            if resp.status_code == 200: response_text = resp.json()['choices'][0]['message']['content']

        elif ACTIVE_LLM == "mistral_local":
            payload = {"model": "mistral", "prompt": prompt, "stream": False, "format": "json"}
            try:
                resp = requests.post(MISTRAL_API_URL, json=payload, timeout=MISTRAL_TIMEOUT)
                if resp.status_code == 200: response_text = resp.json().get('response', '')
            except: return None


        cleaned = response_text.replace("```json", "").replace("```", "").strip()
        return json.loads(cleaned)


    except Exception as e:
        print(f"❌ Warning Generation Error: {e}")
        return None

def process_git_upload():
    data = request.json

    user_id = data.get("user_id")
    project_name = data.get("project_name")
    repo_url = data.get("repo_url")
    branch = data.get("branch", "main")
    token = data.get("token")  # optional

    # -----------------------------
    # BASIC VALIDATION
    # -----------------------------
    user = db.session.get(User, user_id) if user_id else None
    if not user:
        return api_response("User not found", None, 404)

    if not repo_url:
        return api_response("Repository URL required", None, 400)

    # -----------------------------
    # PLAN-BASED SIZE LIMIT
    # -----------------------------
    plan = getattr(user, "subscription_tier", "free")

    if plan == "PREMIUM":
        max_size_bytes = 20 * 1024 * 1024   # 20 MB
    else:
        max_size_bytes = 10 * 1024         # 10 KB    


    # -----------------------------
    # SESSION SETUP
    # -----------------------------
    session_id = str(uuid.uuid4())
    session_folder = os.path.join(UPLOAD_FOLDER, str(user_id), session_id)
    graph_folder = os.path.join(GRAPH_FOLDER, str(user_id), session_id)

    os.makedirs(session_folder, exist_ok=True)
    os.makedirs(graph_folder, exist_ok=True)

    # -----------------------------
    # STEP 1: CLONE REPO
    # -----------------------------
    clone_result = clone_git_repo(
        repo_url=repo_url,
        user_id=user_id,
        session_id=session_id,
        branch=branch,
        token=token
    )

    if clone_result.get("statusCode") != 201:
        return api_response("Failed to clone repository", clone_result, 500)

    # extracted path MUST be resolved AFTER clone
    extracted_path = os.path.join(
        UPLOAD_FOLDER,
        str(user_id),
        session_id,
        "extracted"
    )

    if not os.path.exists(extracted_path):
        return api_response("Extracted repository folder not found", None, 500)

    # -----------------------------
    # STEP 2: CREATE PROJECT
    # -----------------------------
    new_project = Project(
    name=project_name or f"Session_{session_id[:8]}",
    user_id=user.id,
    session_id=session_id,
    code_health_status="PENDING",
    api_analysis_status="PENDING",
    visualization_status="PENDING",
    relationship_status="PENDING"
    )

    db.session.add(new_project)
    db.session.commit()

    # -----------------------------
    # STEP 3: ANALYSIS PIPELINE
    # -----------------------------
    analyzer = PythonAnalyzer()
    relationships = []
    unique_nodes = set()
    files_data = []

    embedding_model = get_embedding_model()
    collection = get_chroma_client().get_or_create_collection(
        name=f"session_{session_id}"
    )

    IGNORE_DIRS = {'.git', '__pycache__', 'node_modules', 'venv', 'env'}

    for root, dirs, files in os.walk(extracted_path):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]

        for f in files:
            file_path = os.path.join(root, f)

            # 🔥 FILE SIZE CHECK
            file_size = os.path.getsize(file_path)

            if file_size > max_size_bytes:
                return api_response(
                    f"File '{f}' exceeds allowed size limit for {plan} plan",
                    {
                        "limit": "20MB" if plan.lower() == "PREMIUM" else "10KB"
                    },
                    403
                )

            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as fr:
                    content = fr.read()
            except Exception:
                continue

            rel_file = os.path.relpath(file_path, extracted_path).replace("\\", "/")
            lines = len(content.splitlines())

            if f.endswith(".py"):
                analyzer.analyze(file_path, relationships, unique_nodes)
            else:
                unique_nodes.add(rel_file)

            risk = min(100, int((content.count("if ") + content.count("for ")) * 1.5))
           
            ext = os.path.splitext(f)[1].lower()

            files_data.append({
                "id": rel_file,
                "filename": rel_file,
                "extension": ext,
                "folder": os.path.dirname(rel_file) or "Root",
                "lines_of_code": lines,
                "risk_score": risk,
                "content": content
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

    # -----------------------------
    # STEP 4: FINALIZATION
    # -----------------------------
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

    baseline = compute_project_baseline(files_data)

    for f in files_data:
        f["metrics"] = analyze_file_metrics(
            f["content"],
            f["lines_of_code"],
            baseline
        )


    code_health = calculate_code_health(files_data)
    if code_health and "ratings" in code_health:
        explanations = generate_health_explanations(
            files_data,
            code_health["ratings"]
        )


        enhanced_ratings = {}
        for key, score in code_health["ratings"].items():
            ai = explanations.get(key, {})
            enhanced_ratings[key] = {
                "score": score,
                "reason": ai.get("reason", ""),
                "suggestion": ai.get("suggestion", ""),
                "affected_files": ai.get("affected_files", []),
                "impact": ai.get("impact", "")
            }

        code_health["ratings"] = enhanced_ratings

    insights = generate_internal_insights(files_data)

    #  STATUS UPDATE HERE
    new_project.code_health_status = "DONE"
    new_project.api_analysis_status = "DONE"
    new_project.visualization_status = "DONE"
    new_project.relationship_status = "DONE"

    db.session.commit()

    upload_entry = Upload(
        project_id=new_project.id,
        session_id=session_id,
        codeHealth=code_health,
        files=files_data,
        insights=insights
    )

    db.session.add(upload_entry)
    db.session.commit()

    return api_response(
        "Git Repository Analyzed",
        {
            "project_id": new_project.id,
            "session_id": session_id
        },
        200
    )


