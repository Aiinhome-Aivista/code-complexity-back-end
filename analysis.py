# import ast
# import re
# import json
# import radon.complexity as radon_cc
# from google import genai

# from config import GEMINI_API_KEY, MODEL_NAME

# client = None
# if GEMINI_API_KEY:
#     client = genai.Client(api_key=GEMINI_API_KEY)


# def check_python_syntax(content):
#     issues = []
#     try:
#         ast.parse(content)
#     except SyntaxError as e:
#         issues.append({
#             "line": e.lineno,
#             "type": "Syntax Error",
#             "severity": "Critical",
#             "title": "Syntax Error",
#             "message": f"{e.msg}",
#             "rule": "python-syntax",
#             "snippet": e.text.strip() if e.text else ""
#         })
#     except Exception as e:
#         pass
#     return issues

# def ai_scan_code(content, filename):
#     if not GEMINI_API_KEY: return []
#     try:
#         model = genai.GenerativeModel(MODEL_NAME)
#         prompt = f"""
#         Act as a strict code compiler. Analyze this code for:
#         1. Syntax Errors
#         2. Logical Errors
#         3. Security Risks
        
#         Ignore comments. Return ONLY a raw JSON array. No Markdown.
#         Format: [{{ "line": <number>, "type": "Bug"|"Security", "severity": "High"|"Medium", "title": "<short title>", "message": "<explanation>", "rule": "<id>" }}]

#         Filename: {filename}
#         Code:
#         {content[:8000]} 
#         """
#         response = model.generate_content(prompt)
#         text = response.text.strip()
#         if text.startswith("```"): text = text.split("\n", 1)[1].rsplit("\n", 1)[0]
#         return json.loads(text)
#     except: return []

# def get_ai_fix(snippet, error, filename="code"):
#     if not GEMINI_API_KEY: return json.dumps({"explanation": "API Key missing.", "fixed_code": snippet})
#     try:
#         model = genai.GenerativeModel(MODEL_NAME)
#         prompt = f"""
#         You are an automated code fixer.
#         The file '{filename}' has an error: "{error}".
#         Snippet: {snippet}
#         Return a RAW JSON object with keys: "explanation" and "fixed_code".
#         Rules: Add 'pass' for empty blocks. Close brackets. Keep indentation.
#         """
#         response = model.generate_content(prompt)
#         text = response.text.strip()
#         if text.startswith("```"): text = text.split("\n", 1)[1].rsplit("\n", 1)[0]
#         return text 
#     except Exception as e:
#         return json.dumps({"explanation": f"AI Error: {str(e)}", "fixed_code": snippet})

# def analyze_code(content, filename):
#     lines = content.split('\n')
#     issues = []
    
#     if filename.endswith('.py'):
#         issues.extend(check_python_syntax(content))

#     if GEMINI_API_KEY and len(issues) == 0:
#         ai_issues = ai_scan_code(content, filename)
#         for issue in ai_issues:
#             line_idx = issue.get('line', 1) - 1
#             if 0 <= line_idx < len(lines):
#                 issue['snippet'] = lines[line_idx].strip()
#             issues.append(issue)

#     try: complexity = sum([b.complexity for b in radon_cc.cc_visit(content)])
#     except: complexity = 0
    
#     security_count = len([i for i in issues if i['type'] in ['Security', 'Syntax', 'Critical']])
#     risk_score = min(100, (complexity * 0.5) + (security_count * 15))

#     return {
#         "complexity": complexity, "security_issues": security_count,
#         "risk_score": int(risk_score), "lines_of_code": len(lines),
#         "issues": json.dumps(issues), "apis": json.dumps([])
#     }






import ast
import json
import requests
import radon.complexity as radon_cc
from google import genai
from config import (
    GEMINI_API_KEY, MODEL_NAME,
    MISTRAL_API_KEY, MISTRAL_MODEL,
    MISTRAL_API_URL, ACTIVE_LLM
)


# --- GEMINI CLIENT ---
client = None
if GEMINI_API_KEY:
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"Gemini Init Error: {e}")


# --- HELPER: CALL MISTRAL (Cloud or Local) ---
def call_mistral_ai(prompt):
    """
    Calls Mistral AI (Cloud or Local) based on config.
    Returns: (json_content, usage_dict)
    """
    is_local = "local" in ACTIVE_LLM
   
    # 1. Setup URL and Headers
    if is_local:
        url = MISTRAL_API_URL # e.g., http://localhost:11434/api/generate (Ollama)
        headers = {"Content-Type": "application/json"}
        payload = {
            "model": MISTRAL_MODEL,
            "prompt": prompt,
            "stream": False,
            "format": "json" # Ollama supports JSON mode
        }
    else:
        # Mistral Cloud
        if not MISTRAL_API_KEY:
            print("❌ Mistral API Key missing")
            return [], None
           
        url = "https://api.mistral.ai/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {MISTRAL_API_KEY}"
        }
        payload = {
            "model": MISTRAL_MODEL or "mistral-small-latest",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "response_format": {"type": "json_object"}
        }


    try:
        print(f"⚡ Requesting {ACTIVE_LLM}...")
        response = requests.post(url, headers=headers, json=payload)
       
        if response.status_code == 200:
            data = response.json()
            usage = None
            content = []


            # 2. Parse Response & Usage
            if is_local:
                # OLLAMA Response Format
                raw_text = data.get("response", "")
                input_tokens = data.get("prompt_eval_count", 0)
                output_tokens = data.get("eval_count", 0)
                usage = {"input": input_tokens, "output": output_tokens, "provider": "mistral_local"}
            else:
                # MISTRAL CLOUD Response Format
                raw_text = data['choices'][0]['message']['content']
                usage_data = data.get("usage", {})
                usage = {
                    "input": usage_data.get("prompt_tokens", 0),
                    "output": usage_data.get("completion_tokens", 0),
                    "provider": "mistral_cloud"
                }


            # 3. Clean and Parse JSON Content
            if raw_text.startswith("```"):
                raw_text = raw_text.split("\n", 1)[1].rsplit("\n", 1)[0]
           
            try:
                content = json.loads(raw_text)
                # Ensure it's a list for scan results
                if isinstance(content, dict) and "issues" in content:
                    content = content["issues"]
            except:
                content = [] # Fallback


            return content, usage
        else:
            print(f"Mistral Error {response.status_code}: {response.text}")
            return [], None
    except Exception as e:
        print(f"Mistral Exception: {e}")
        return [], None


# --- HELPER: CALL GEMINI ---
def call_gemini_ai(prompt):
    """
    Calls Gemini AI.
    Returns: (json_content, usage_dict)
    """
    if not client:
        print("❌ Gemini Client not initialized")
        return [], None


    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt
        )
       
        # Extract Usage
        usage = None
        if response.usage_metadata:
            usage = {
                "input": response.usage_metadata.prompt_token_count,
                "output": response.usage_metadata.candidates_token_count,
                "provider": "gemini"
            }


        # Parse Content
        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("\n", 1)[0]
       
        try:
            return json.loads(text), usage
        except:
            return [], usage


    except Exception as e:
        print(f"Gemini Error: {e}")
        # If Quota exceeded and ACTIVE_LLM allows fallback, we could switch,
        # but requested behavior is strict config. Returning None to signal failure.
        return [], None


# --- MAIN ANALYSIS FUNCTION ---
def ai_scan_code_detailed(content, filename):
    """
    Analyzes code using the ACTIVE_LLM defined in config.py.
    Returns tuple: (issues_list, usage_dict)
    """
    prompt = f"""
    You are a code security expert. Analyze '{filename}'.
    Return a RAW JSON ARRAY of issues. Format:
    [
        {{
            "line": <number>,
            "type": "Security"|"Performance"|"Bug",
            "severity": "High"|"Medium"|"Low",
            "title": "<short title>",
            "suggested_explanation": "<detailed fix>",
            "original_snippet": "<the exact lines of code with the issue>",
            "suggested_fix": "<the corrected version of that snippet>"

        }}
    ]
    Code:
    {content[:20000]}
    """
   
    # Route based on Config
    if "mistral" in ACTIVE_LLM:
        return call_mistral_ai(prompt)
    else:
        # Default to Gemini
        return call_gemini_ai(prompt)


# --- AI FIX FUNCTION ---
def get_ai_fix(snippet, error, filename="code"):
    prompt = f"""
    Fix this code error. Return JSON: {{ "explanation": "...", "fixed_code": "..." }}
    Error: "{error}"
    Snippet:
    {snippet}
    """
   
    result = None
    usage = None


    if "mistral" in ACTIVE_LLM:
        result, usage = call_mistral_ai(prompt)
    else:
        result, usage = call_gemini_ai(prompt)
       
    # Handle response format (might be dict, not list)
    if isinstance(result, list):
        # Mistral might return list if reusing same parser
        return json.dumps({"explanation": "Analysis failed", "fixed_code": snippet}), usage
       
    return json.dumps(result) if result else json.dumps({"explanation": "AI failed", "fixed_code": snippet}), usage


def analyze_code(content, filename):
    lines = content.split('\n')
    issues = []
   
    # 1. Static Syntax Check
    if filename.endswith('.py'):
        try:
            ast.parse(content)
        except SyntaxError as e:
            issues.append({
                "line": e.lineno,
                "type": "Syntax Error",
                "severity": "Critical",
                "title": "Syntax Error",
                "message": str(e),
                "snippet": e.text.strip() if e.text else ""
            })


    # 2. Complexity Check
    try: complexity = sum([b.complexity for b in radon_cc.cc_visit(content)])
    except: complexity = 0
   
    # Note: Full AI Scan happens in controller to manage tokens/async better
    # We return basic static metrics here
    security_count = len([i for i in issues if i['type'] in ['Security', 'Critical']])
    risk_score = min(100, (complexity * 0.5) + (security_count * 15))


    return {
        "complexity": complexity,
        "security_issues": security_count,
        "risk_score": int(risk_score),
        "lines_of_code": len(lines),
        "issues": json.dumps(issues),
        "apis": json.dumps([])
    }



