import json
import requests
from config import (
    ACTIVE_LLM,
    GEMINI_API_KEY,
    MISTRAL_TIMEOUT,
    MODEL_NAME,
    MISTRAL_API_KEY,
    MISTRAL_MODEL,
    MISTRAL_API_URL
)

try:
    from google import genai
    gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
except:
    gemini_client = None


def refine_flow_with_ai(flow_nodes, files_data):
    """
    AI refines:
    - missing dependencies
    - wrong categories
    - noisy fields
    """
    prompt = f"""
You are a software architecture analyzer.

You are given:
1. Initial dependency graph (may be incomplete)
2. Source code files

TASK:
- Fix missing or wrong file dependencies
- Improve category (api, util, model, component, config)
- Remove unimportant fields, keep public/meaningful ones

STRICT RULES:
- Do NOT invent files
- Do NOT change node id or name
- Return SAME schema

Return ONLY valid JSON:
{{ "nodes": [ {{id, category, dependencies, fields}} ] }}

INITIAL_GRAPH:
{json.dumps(flow_nodes)}

FILES:
{json.dumps([
    {"filename": f["filename"], "content": f["content"][:2000]}
    for f in files_data
])}
"""

    # ---------------- GEMINI ----------------
    if ACTIVE_LLM == "gemini" and gemini_client:
        resp = gemini_client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt
        )
        text = resp.text

    # ---------------- MISTRAL CLOUD ----------------
    elif ACTIVE_LLM == "mistral_cloud" and MISTRAL_API_KEY:
        headers = {
            "Authorization": f"Bearer {MISTRAL_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": MISTRAL_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"}
        }
        resp = requests.post(MISTRAL_API_URL, json=payload, timeout=MISTRAL_TIMEOUT)
        text = resp.json()["choices"][0]["message"]["content"]

    # ---------------- LOCAL MISTRAL ----------------
    elif ACTIVE_LLM == "mistral_local":
        payload = {
            "model": "mistral",
            "prompt": prompt,
            "stream": False,
            "format": "json"
        }
        resp = requests.post(MISTRAL_API_URL, json=payload, timeout=MISTRAL_TIMEOUT)
        text = resp.json().get("response", "")

    else:
        return flow_nodes   # fallback

    # -------- Parse safely --------
    try:
        cleaned = text.replace("```json", "").replace("```", "").strip()
        ai_data = json.loads(cleaned)
        refined = {n["id"]: n for n in ai_data.get("nodes", [])}

        # merge AI output with original
        for n in flow_nodes:
            if n["id"] in refined:
                n.update({
                    "category": refined[n["id"]].get("category", n["category"]),
                    "dependencies": refined[n["id"]].get("dependencies", n["dependencies"]),
                    "fields": refined[n["id"]].get("fields", n["fields"]),
                })

        return flow_nodes

    except Exception:
        return flow_nodes


