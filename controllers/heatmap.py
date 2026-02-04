import json
import requests
from google import genai
from flask import request
from models import Project, db, User, Upload
from utils.response import api_response
from config import (
    ACTIVE_LLM,
    GEMINI_API_KEY,
    MISTRAL_API_KEY,
    MISTRAL_API_URL,
    MISTRAL_MODEL,
    MODEL_NAME
)


AI_HEATMAP_CACHE = {}

# ===============================
# Gemini Client (lazy safe)
# ===============================
client = None
if GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY)


# ===============================
# Risk Level Resolver (UI legend match)
# ===============================
def resolve_risk_level(score: int) -> str:
    if score < 20:
        return "safe"
    if score < 40:
        return "low"
    if score < 60:
        return "moderate"
    if score < 80:
        return "high"
    return "critical"


# ===============================
# CORE: AI-based File Risk Scoring
# ===============================
def ai_score_file(file_content: str, metric: str):
    # We update the prompt to demand the 3 specific areas in JSON format
    prompt = f"""
You are a senior software auditor.

Evaluate the RISK (0-100) of the following source code for the metric: {metric}

Metric meaning:
- complexity: nesting, control flow, maintainability
- security: injections, auth flaws, unsafe patterns
- performance: blocking calls, heavy loops, inefficiency
- size: oversized file, too many responsibilities

Return ONLY valid JSON:
{{
  "risk": 0,
  "reason": "Explain why it is low, high, or moderate",
  "solution": "Clear steps to fix or improve this specific issue",
  "suggested_code": "A short code snippet showing the improved version"
}}

SOURCE CODE:
{file_content[:3500]}
"""
    response_text = ""

    # ---------- GEMINI ----------
    if ACTIVE_LLM == "gemini":
        if not GEMINI_API_KEY or not client:
            return {"risk": 0, "reason": "Gemini API key missing", "solution": "", "suggested_code": ""}

        try:
            resp = client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt
            )
            response_text = resp.text
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                return ai_score_file_fallback(prompt)
            else:
                raise

    # ---------- MISTRAL CLOUD ----------
    elif ACTIVE_LLM == "mistral_cloud":
        if not MISTRAL_API_KEY:
            return {"risk": 0, "reason": "Mistral API key missing", "solution": "", "suggested_code": ""}
        
        headers = {"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": MISTRAL_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"}
        }
        resp = requests.post("https://api.mistral.ai/v1/chat/completions", json=payload, headers=headers, timeout=60)
        response_text = resp.json()["choices"][0]["message"]["content"]

    # ---------- MISTRAL LOCAL ----------
    elif ACTIVE_LLM == "mistral_local":
        payload = {"model": "mistral", "prompt": prompt, "stream": False, "format": "json"}
        resp = requests.post(MISTRAL_API_URL, json=payload, timeout=60)
        response_text = resp.json().get("response", "")
    
    else:
        return {"risk": 0, "reason": "Invalid AI configuration", "solution": "", "suggested_code": ""}

    # Parse and clean the response
    try:
        cleaned = response_text.replace("```json", "").replace("```", "").strip()
        return json.loads(cleaned)
    except Exception:
        return {
            "risk": 0, 
            "reason": "Error parsing AI response", 
            "solution": "Manual review required", 
            "suggested_code": ""
        }

def ai_score_file_fallback(prompt: str):
    """
    Fallback order:
    1. Mistral Cloud
    2. Local Mistral
    """
    # ---- MISTRAL CLOUD ----
    if MISTRAL_API_KEY:
        headers = {
            "Authorization": f"Bearer {MISTRAL_API_KEY}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": MISTRAL_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"}
        }

        try:
            resp = requests.post(
                "https://api.mistral.ai/v1/chat/completions",
                json=payload,
                headers=headers,
                timeout=60
            )

            if resp.status_code == 200:
                return json.loads(resp.json()["choices"][0]["message"]["content"])
        except:
            pass # Move to local if cloud fails

    # ---- LOCAL MISTRAL ----
    try:
        payload = {
            "model": "mistral",
            "prompt": prompt,
            "stream": False,
            "format": "json"
        }
        resp = requests.post(MISTRAL_API_URL, json=payload, timeout=60)
        return json.loads(resp.json().get("response", "{}"))
    except:
        # Final emergency return if everything fails
        return {
            "risk": 0, 
            "reason": "AI service unavailable", 
            "solution": "Check API keys or Local LLM status", 
            "suggested_code": ""
        }

# ===============================
#  AI HEATMAP API (SINGLE ROUTE)
# ===============================

def code_risk_heatmap():
    try:
        # 1. Get request data
        payload = request.get_json() or {}
        project_id = payload.get("project_id")
        session_id = payload.get("session_id")
        metric = payload.get("metric")

        # 2. Validate required fields
        if not project_id or not session_id or not metric:
            return api_response("project_id, session_id and metric are required", None, 400)

        # 3. Look up project and upload records in the database
        project = Project.query.get(project_id)
        upload = Upload.query.filter_by(project_id=project_id, session_id=session_id).first()

        if not project or not upload:
            return api_response("Project or Upload not found", None, 404)

        # 4. Check if heatmap is already cached in the database
        # --- UPDATED CACHE CHECK ---
        if upload.heatmap:
            # Check if the saved heatmap metric matches the requested metric
            cached_data = upload.heatmap
            if cached_data.get("metric") == metric:
                print(f"[HEATMAP] Returning cached results for {metric}")
                project.heatmap_status = "DONE"
                db.session.commit()
                return api_response("AI Heatmap (Cached)", upload.heatmap, 200)
            else:
                print(f"[HEATMAP] Metric changed from {cached_data.get('metric')} to {metric}. Re-analyzing...")
        # We don't return here, so the code continues to the AI analysis below

        # 5. Set status to PENDING while we process
        project.heatmap_status = "PENDING"
        db.session.commit() # Save pending status to db

        files = upload.files or []
        heatmap_files = []

        # 6. Loop through each file to generate AI analysis
        for f in files:
            cache_key = f"{project_id}:{session_id}:{metric}:{f.get('filename')}"

            # Check if this specific file result is in memory cache
            if cache_key in AI_HEATMAP_CACHE:
                ai_result = AI_HEATMAP_CACHE[cache_key]
            else:
                # Call AI scoring function
                ai_result = ai_score_file(f.get("content", ""), metric)
                # Store result in memory cache
                AI_HEATMAP_CACHE[cache_key] = ai_result

            # Process the score
            score = int(ai_result.get("risk", 0))
            score = max(0, min(100, score))

            # 7. Build the file data object with the 3 new areas
            heatmap_files.append({
                "filename": f.get("filename"),
                "risk": score,
                "risk_level": resolve_risk_level(score),
                "reason": ai_result.get("reason", ""),           # Added: Why it's low/high
                "solution": ai_result.get("solution", ""),       # Added: How to fix it
                "suggested_code": ai_result.get("suggested_code", ""), # Added: Improved code snippet
                "lines": f.get("lines_of_code", 0)
            })

        # 8. Prepare final heatmap structure
        heatmap_data = {
            "metric": metric,
            "legend": {
                "safe": "0-19", "low": "20-39", "moderate": "40-59", 
                "high": "60-79", "critical": "80-100"
            },
            "files": heatmap_files
        }

        # 9. SAVE TO DB: Update the upload record and project status
        upload.heatmap = heatmap_data
        project.heatmap_status = "DONE"
        db.session.commit() # Save everything to database

        # 10. Return the final data to the user
        return api_response("AI Heatmap Generated", heatmap_data, 200)

    except Exception as e:
        # Log the error and return failure
        print("AI Heatmap Error:", e)
        return api_response("Internal Server Error", None, 500)

