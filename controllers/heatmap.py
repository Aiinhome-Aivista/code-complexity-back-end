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

# ✅ Supported metrics
SUPPORTED_METRICS = ["complexity", "security", "performance", "size"]

#  Files to ignore in AI scoring
SKIP_FILES = {
    ".gitignore",
    "README.md",
    "README",
    "requirements.txt",
    "package-lock.json",
    "yarn.lock",
    "Pipfile",
    "Pipfile.lock"
}

#  Extensions to ignore
SKIP_EXTENSIONS = {
    ".md",
    ".txt",
    ".lock",
    ".log"
}



# ===============================
# Gemini Client (lazy safe)
# ===============================
client = None
if GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY)


# ===============================
# Helpers
# ===============================
def resolve_risk_level(score: int) -> str:
    if score < 20: return "safe"
    if score < 40: return "low"
    if score < 60: return "moderate"
    if score < 80: return "high"
    return "critical"

def extract_json_from_ai(text: str):
    """Finds JSON even if AI includes backticks or conversational text."""
    try:
        # Locate the first '{' and the last '}'
        start = text.find('{')
        end = text.rfind('}') + 1
        if start != -1 and end != 0:
            data = json.loads(text[start:end])
            
            # Post-process to calculate suggested_lines immediately
            s_code = data.get("suggested_code", "")
            if (isinstance(s_code, str) and 
                len(s_code.strip()) > 5 and 
                s_code.upper() not in ["N/A", "NONE", "NO CHANGES REQUIRED.", "NO CHANGES"]):
                data["suggested_lines"] = len(s_code.splitlines())
            else:
                data["suggested_lines"] = 0
            return data
    except Exception as e:
        print(f"JSON Parse Error: {e}")
    return None


# ===============================
# CORE: AI-based File Risk Scoring
# ===============================
def ai_score_file(file_content: str, metric: str):
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

    if ACTIVE_LLM == "gemini":
        if not GEMINI_API_KEY or not client:
            return {"risk": 0, "reason": "Gemini API key missing", "solution": "", "suggested_code": "", "suggested_lines": 0}
        try:
            resp = client.models.generate_content(model=MODEL_NAME, contents=prompt)
            response_text = resp.text
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                return ai_score_file_fallback(prompt)
            else:
                raise

    elif ACTIVE_LLM == "mistral_cloud":
        if not MISTRAL_API_KEY:
            return {"risk": 0, "reason": "Mistral API key missing", "solution": "", "suggested_code": "", "suggested_lines": 0}
        headers = {"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": MISTRAL_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"}
        }
        resp = requests.post("https://api.mistral.ai/v1/chat/completions", json=payload, headers=headers, timeout=60)
        response_text = resp.json()["choices"][0]["message"]["content"]

    elif ACTIVE_LLM == "mistral_local":
        payload = {"model": "mistral", "prompt": prompt, "stream": False, "format": "json"}
        resp = requests.post(MISTRAL_API_URL, json=payload, timeout=60)
        response_text = resp.json().get("response", "")

    # Process response using our helper
    result = extract_json_from_ai(response_text)
    if result:
        return result
    
    return {
        "risk": 0, "reason": "Failed to parse AI response", "solution": "Manual review", "suggested_code": "", "suggested_lines": 0
    }

def ai_score_file_fallback(prompt: str):
    """Fallback logic if primary LLM fails."""
    try:
        if MISTRAL_API_KEY:
            headers = {"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"}
            payload = {
                "model": MISTRAL_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"}
            }
            resp = requests.post("https://api.mistral.ai/v1/chat/completions", json=payload, headers=headers, timeout=60)
            if resp.status_code == 200:
                return extract_json_from_ai(resp.json()["choices"][0]["message"]["content"])
    except:
        pass

    try:
        payload = {"model": "mistral", "prompt": prompt, "stream": False, "format": "json"}
        resp = requests.post(MISTRAL_API_URL, json=payload, timeout=60)
        return extract_json_from_ai(resp.json().get("response", "{}"))
    except:
        return {
            "risk": 0, "reason": "AI service unavailable", "solution": "Check connection", "suggested_code": "", "suggested_lines": 0
        }


# ===============================
#  AI HEATMAP API (SINGLE ROUTE)
# ===============================
METRIC_WEIGHTS = {
    "complexity": 1.2,
    "security": 1.5,
    "performance": 1.0,
    "size": 0.8
}

def code_risk_heatmap():
    try:
        payload = request.get_json() or {}
        project_id = payload.get("project_id")
        session_id = payload.get("session_id")
        requested_metrics = payload.get("metrics", SUPPORTED_METRICS)
        force_refresh = payload.get("force", False)

        if not project_id or not session_id:
            return api_response("project_id and session_id required", None, 400)

        project = Project.query.get(project_id)
        upload = Upload.query.filter_by(
            project_id=project_id,
            session_id=session_id
        ).first()

        if not project or not upload:
            return api_response("Project not found", None, 404)

        project.heatmap_status = "PENDING"
        db.session.commit()

        files = upload.files or []
        final_heatmap = {}
        project_summary = {}

        overall_scores = []

        for metric in requested_metrics:

            if metric not in SUPPORTED_METRICS:
                continue

            heatmap_files = []

            for f in files:

                filename = f.get("filename", "")
                extension = ""

                if "." in filename:
                    extension = "." + filename.split(".")[-1].lower()

                #  Skip unwanted files
                if (
                    filename in SKIP_FILES
                    or extension in SKIP_EXTENSIONS
                    or filename.startswith(".")
                ):
                    continue


                cache_key = f"{project_id}:{session_id}:{metric}:{f.get('filename')}"

                if not force_refresh and cache_key in AI_HEATMAP_CACHE:
                    ai_result = AI_HEATMAP_CACHE[cache_key]
                else:
                    ai_result = ai_score_file(f.get("content", ""), metric)
                    AI_HEATMAP_CACHE[cache_key] = ai_result

                raw_score = int(ai_result.get("risk", 0))
                raw_score = max(0, min(100, raw_score))

                weighted_score = int(raw_score * METRIC_WEIGHTS.get(metric, 1))
                weighted_score = min(weighted_score, 100)

                density = 0
                if f.get("lines_of_code", 0) > 0:
                    density = round(weighted_score / f["lines_of_code"], 2)

                overall_scores.append(weighted_score)

                heatmap_files.append({
                    "filename": f.get("filename"),
                    "risk": weighted_score,
                    "risk_level": resolve_risk_level(weighted_score),
                    "risk_density": density,
                    "reason": ai_result.get("reason", ""),
                    "solution": ai_result.get("solution", ""),
                    "suggested_code": ai_result.get("suggested_code", ""),
                    "suggested_lines": ai_result.get("suggested_lines", 0),
                    "lines": f.get("lines_of_code", 0)
                })

            #  Sort by risk descending
            heatmap_files.sort(key=lambda x: x["risk"], reverse=True)

            final_heatmap[metric] = {
                "legend": {
                    "safe": "0-19",
                    "low": "20-39",
                    "moderate": "40-59",
                    "high": "60-79",
                    "critical": "80-100"
                },
                "files": heatmap_files
            }

        #  PROJECT LEVEL SUMMARY
        if overall_scores:
            avg_risk = int(sum(overall_scores) / len(overall_scores))
            critical_count = len([s for s in overall_scores if s >= 80])
            high_count = len([s for s in overall_scores if s >= 60])

            project_summary = {
                "overall_risk_score": avg_risk,
                "overall_risk_level": resolve_risk_level(avg_risk),
                "critical_files": critical_count,
                "high_risk_files": high_count,
                "total_files": len(files)
            }

        heatmap_data = {
            "summary": project_summary,
            "metrics": final_heatmap
        }

        upload.heatmap = heatmap_data
        project.heatmap_status = "DONE"
        db.session.commit()

        return api_response("AI Heatmap Generated", heatmap_data, 200)

    except Exception as e:
        print("AI Heatmap Error:", e)
        return api_response("Internal Server Error", None, 500)


