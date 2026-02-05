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

# ✅ NEW: supported metrics (ONLY ADDITION)
SUPPORTED_METRICS = ["complexity", "security", "performance", "size"]


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

    elif ACTIVE_LLM == "mistral_cloud":
        if not MISTRAL_API_KEY:
            return {"risk": 0, "reason": "Mistral API key missing", "solution": "", "suggested_code": ""}

        headers = {"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": MISTRAL_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"}
        }
        resp = requests.post(
            "https://api.mistral.ai/v1/chat/completions",
            json=payload,
            headers=headers,
            timeout=60
        )
        response_text = resp.json()["choices"][0]["message"]["content"]

    elif ACTIVE_LLM == "mistral_local":
        payload = {"model": "mistral", "prompt": prompt, "stream": False, "format": "json"}
        resp = requests.post(MISTRAL_API_URL, json=payload, timeout=60)
        response_text = resp.json().get("response", "")

    else:
        return {"risk": 0, "reason": "Invalid AI configuration", "solution": "", "suggested_code": ""}

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
            pass

    try:
        payload = {"model": "mistral", "prompt": prompt, "stream": False, "format": "json"}
        resp = requests.post(MISTRAL_API_URL, json=payload, timeout=60)
        return json.loads(resp.json().get("response", "{}"))
    except:
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
        payload = request.get_json() or {}
        project_id = payload.get("project_id")
        session_id = payload.get("session_id")

        # ✅ metric removed from validation
        if not project_id or not session_id:
            return api_response("project_id and session_id are required", None, 400)

        project = Project.query.get(project_id)
        upload = Upload.query.filter_by(
            project_id=project_id,
            session_id=session_id
        ).first()

        if not project or not upload:
            return api_response("Project or Upload not found", None, 404)

        # ✅ cache check for multi-metric
        if upload.heatmap and upload.heatmap.get("metrics"):
            project.heatmap_status = "DONE"
            db.session.commit()
            return api_response("AI Heatmap (Cached)", upload.heatmap, 200)

        project.heatmap_status = "PENDING"
        db.session.commit()

        files = upload.files or []
        final_heatmap = {}

        # ✅ MULTI METRIC LOOP (CORE CHANGE)
        for metric in SUPPORTED_METRICS:
            heatmap_files = []

            for f in files:
                cache_key = f"{project_id}:{session_id}:{metric}:{f.get('filename')}"

                if cache_key in AI_HEATMAP_CACHE:
                    ai_result = AI_HEATMAP_CACHE[cache_key]
                else:
                    ai_result = ai_score_file(f.get("content", ""), metric)
                    AI_HEATMAP_CACHE[cache_key] = ai_result

                score = int(ai_result.get("risk", 0))
                score = max(0, min(100, score))

                heatmap_files.append({
                    "filename": f.get("filename"),
                    "risk": score,
                    "risk_level": resolve_risk_level(score),
                    "reason": ai_result.get("reason", ""),
                    "solution": ai_result.get("solution", ""),
                    "suggested_code": ai_result.get("suggested_code", ""),
                    "lines": f.get("lines_of_code", 0)
                })

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

        heatmap_data = {"metrics": final_heatmap}

        upload.heatmap = heatmap_data
        project.heatmap_status = "DONE"
        db.session.commit()

        return api_response("AI Heatmap Generated", heatmap_data, 200)

    except Exception as e:
        print("AI Heatmap Error:", e)
        return api_response("Internal Server Error", None, 500)


