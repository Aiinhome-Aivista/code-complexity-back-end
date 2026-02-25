import random


def generate_math_captcha():
    num1 = random.randint(1, 20)
    num2 = random.randint(1, 20)
    # We return the question to show the user 
    # and the answer to store in our database/session
    return {
        "question": f"{num1} + {num2} =?",
        "answer": str(num1 + num2)
    }