from google import genai
from models import FileAnalysis
from flask import Blueprint, request
from utils.response import api_response
from config import GEMINI_API_KEY, MODEL_NAME

insight_bp = Blueprint('insight_bp', __name__)

client = None
if GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY)


def generate_project_insights():
    data = request.json
    project_id = data.get('project_id')

    if not project_id:
        return api_response("Project ID required", None, 400)

    files = FileAnalysis.query.filter_by(project_id=project_id).all()
    if not files:
        return api_response("No files found", None, 404)

    file_summary = "\n".join(
        [f"- {f.filename} (Risk: {f.risk_score})" for f in files[:20]]
    )

    prompt = f"""
    Analyze the following project structure and risk scores:
    {file_summary}

    Provide 3 concise, high-value architectural insights or refactoring recommendations.
    Format as JSON: {{ "insights": ["Insight 1", "Insight 2", "Insight 3"] }}
    """

    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt
        )

        text = (
            response.text
            .replace("```json", "")
            .replace("```", "")
            .strip()
        )

        return api_response("Insights Generated", text, 200)

    except Exception as e:
        return api_response(f"AI Error: {str(e)}", None, 500)


