import random
from itsdangerous import URLSafeSerializer
from flask import current_app

def generate_math_captcha():
    num1 = random.randint(1, 20)
    num2 = random.randint(1, 20)

    return {
        "question": f"{num1} + {num2} =?",
        "answer": str(num1 + num2)
    }


