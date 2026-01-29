from flask import request
from models import db, User
from utils.response import api_response
from werkzeug.security import generate_password_hash, check_password_hash

def register():
    data = request.json
    if not data or 'email' not in data: 
        return api_response("Invalid data", None, 400)
    if User.query.filter_by(email=data['email']).first(): 
        return api_response("Email exists", None, 400)
    
    new_user = User(
        name=data.get('name', 'User'), email=data['email'], 
        password_hash=generate_password_hash(data['password']), subscription_tier='free'
    )
    db.session.add(new_user)
    db.session.commit()
    return api_response("Registered", None, 200)

def login():
    data = request.json
    user = User.query.filter_by(email=data.get('email')).first()
    if user and check_password_hash(user.password_hash, data.get('password')):
        return api_response("Success", {"id": user.id, "name": user.name, "email": user.email, "tier": user.subscription_tier}, 200)
    return api_response("Invalid credentials", None, 401)