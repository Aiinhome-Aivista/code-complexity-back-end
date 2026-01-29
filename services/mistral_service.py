import os
import subprocess
import requests
from config import MISTRAL_API_KEY, MISTRAL_MODEL, MISTRAL_BASE_URL




def run_mistral(prompt: str) -> str:
    """
    Auto-switch between:
    1. Mistral API
    2. Local Mistral (Ollama / LM Studio)
    """


    # ------------------------------
    # 1️⃣ MISTRAL CLOUD API
    # ------------------------------
    if MISTRAL_API_KEY:
        headers = {
            "Authorization": f"Bearer {MISTRAL_API_KEY}",
            "Content-Type": "application/json"
        }


        payload = {
            "model": MISTRAL_MODEL,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2
        }


        response = requests.post(
            MISTRAL_BASE_URL,
            headers=headers,
            json=payload,
            timeout=60
        )


        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]


    # ------------------------------
    # 2️⃣ LOCAL MISTRAL (OLLAMA)
    # ------------------------------
    try:
        result = subprocess.run(
            ["ollama", "run", MISTRAL_MODEL],
            input=prompt,
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except Exception as e:
        raise RuntimeError(f"Local Mistral failed: {str(e)}")




