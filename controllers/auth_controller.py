# from flask import request
# from models import db, User
# from utils.response import api_response
# from werkzeug.security import generate_password_hash, check_password_hash

# def register():
#     data = request.json
#     if not data or 'email' not in data: 
#         return api_response("Invalid data", None, 400)
#     if User.query.filter_by(email=data['email']).first(): 
#         return api_response("Email exists", None, 400)
    
#     new_user = User(
#         name=data.get('name', 'User'), email=data['email'], 
#         password_hash=generate_password_hash(data['password']), subscription_tier='free'
#     )
#     db.session.add(new_user)
#     db.session.commit()
#     return api_response("Registered", None, 200)

# def login():
#     data = request.json
#     user = User.query.filter_by(email=data.get('email')).first()
#     if user and check_password_hash(user.password_hash, data.get('password')):
#         return api_response("Success", {"id": user.id, "name": user.name, "email": user.email, "tier": user.subscription_tier}, 200)
#     return api_response("Invalid credentials", None, 401)

from flask import request, url_for, current_app
from flask import render_template_string
from flask_mail import Message
from extensions import db, mail
from models import User
from utils.response import api_response
from utils.token import generate_confirmation_token, confirm_token
from werkzeug.security import generate_password_hash, check_password_hash

# --- HELPER FUNCTION FOR EMAILS ---
def send_email(to, subject, template):
    # We use current_app to access config since the app is initialized elsewhere
    msg = Message(
        subject,
        recipients=[to],
        html=template,
        sender=current_app.config['MAIL_DEFAULT_SENDER']
    )
    mail.send(msg)


def register():
    data = request.json
    if not data or 'email' not in data or 'password' not in data: 
        return api_response("Invalid data", None, 400)
    
    if User.query.filter_by(email=data['email']).first(): 
        return api_response("Email exists", None, 400)
    
    new_user = User(
        name=data.get('name', 'User'), 
        email=data['email'], 
        password_hash=generate_password_hash(data['password']), 
        subscription_tier='free',
        is_active=False
    )
    db.session.add(new_user)
    db.session.commit()

    token = generate_confirmation_token(new_user.email)
    
    # 'activate_account' refers to the name of the route function in app.py
    confirm_url = url_for('activate_account', token=token, _external=True)
    
    html_content = f"""
    <p>Welcome {new_user.name}!</p>
    <p>Please click the link below to activate your account:</p>
    <p><a href="{confirm_url}">Activate Account</a></p>
    <p>This link will expire in 1 hour.</p>
    """
    send_email(new_user.email, "Activate Your Account", html_content)
    
    return api_response("Registered! Please check your email to activate your account.", None, 200)


def activate_account(token):
    email = confirm_token(token)

    if not email:
        return render_template_string("""
            <h2 style="color:red;">❌ Activation Link Expired</h2>
            <p>The confirmation link is invalid or has expired.</p>
        """)

    user = User.query.filter_by(email=email).first()

    if not user:
        return render_template_string("""
            <h2 style="color:red;">❌ User Not Found</h2>
            <p>No account found for this email.</p>
        """)

    if user.is_active:
        return render_template_string("""
            <h2 style="color:green;">✅ Already Activated</h2>
            <p>Your account is already active. Please login.</p>
        """)

    user.is_active = True
    db.session.commit()

    return render_template_string("""
        <h2 style="color:green;">🎉 Account Activated Successfully</h2>
        <p>You can now close this page and login.</p>
    """)


def login():
    data = request.json
    user = User.query.filter_by(email=data.get('email')).first()
    
    if user and check_password_hash(user.password_hash, data.get('password')):
        if not user.is_active:
            return api_response("Please activate your account via the link sent to your email.", None, 403)
            
        return api_response(" Login Successful", {"id": user.id, "name": user.name, "email": user.email, "tier": user.subscription_tier}, 200)
        
    return api_response("Invalid credentials", None, 401)