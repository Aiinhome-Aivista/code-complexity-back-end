from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    subscription_tier = db.Column(db.String(20), default='free')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    projects = db.relationship('Project', backref='user', lazy=True)

class Project(db.Model):
    __tablename__ = "projects"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    name = db.Column(db.String(100), nullable=False)
    session_id = db.Column(db.String(50))
    files_analyzed = db.Column(db.Text)

    visualization_status = db.Column(db.String(50), default="PENDING")
    code_health_status = db.Column(db.String(50), default="PENDING")
    api_analysis_status = db.Column(db.String(50), default="PENDING")
    relationship_status = db.Column(db.String(50), default="PENDING")
    heatmap_status = db.Column(db.String(50), default="PENDING")

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False
    )

class FileAnalysis(db.Model):
    __tablename__ = 'file_analysis'
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    content = db.Column(db.Text)
    applied_fixes = db.Column(db.JSON, default=list)

    
    # Metrics
    complexity = db.Column(db.Integer)
    security_issues = db.Column(db.Integer)
    risk_score = db.Column(db.Integer)
    lines_of_code = db.Column(db.Integer)
    
    # JSON Data
    issues_json = db.Column(db.Text) 
    api_json = db.Column(db.Text)
    
    def to_dict(self):
        return {
            "id": self.id,
            "filename": self.filename,
            "content": self.content,
            "complexity": self.complexity,
            "security_issues": self.security_issues,
            "risk_score": self.risk_score,
            "lines_of_code": self.lines_of_code,
            "issues": self.issues_json,
            "apis": self.api_json
        }



class Upload(db.Model):
    __tablename__ = "upload"


    id = db.Column(db.Integer, primary_key=True)


    project_id = db.Column(db.Integer, nullable=False)
    session_id = db.Column(db.String(50), nullable=False)


    graph_url = db.Column(db.Text)


    codeHealth = db.Column(db.JSON)
    endpointHealth = db.Column(db.JSON)
    files = db.Column(db.JSON)
    insights = db.Column(db.JSON)
    relationships = db.Column(db.JSON)
    heatmap = db.Column(db.JSON)
    analyze_data = db.Column(db.JSON) 


    created_at = db.Column(db.DateTime, default=db.func.now())


# --- Token Usage Table (MISSING CLASS ADDED HERE) ---
class TokenUsage(db.Model):
    __tablename__ = 'token_usage'


    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    session_id = db.Column(db.String(50), nullable=True)
   
    provider = db.Column(db.String(50), nullable=False)    # 'gemini', 'mistral_cloud'
    model_name = db.Column(db.String(100), nullable=False) # 'gemini-1.5-flash'
   
    input_tokens = db.Column(db.Integer, default=0)
    output_tokens = db.Column(db.Integer, default=0)
    total_tokens = db.Column(db.Integer, default=0)
   
    estimated_cost = db.Column(db.Float, default=0.0)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


    def __repr__(self):
        return f"<TokenUsage {self.provider} | {self.total_tokens} tokens>"

class AppliedFix(db.Model):
    __tablename__ = "applied_fix"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    session_id = db.Column(db.String(100), nullable=False)
    modified_code = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

class Plan(db.Model):
    __tablename__ = "plans"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)  # FREE / PREMIUM

    max_upload_size = db.Column(db.BigInteger, nullable=False)  # bytes
    git_access = db.Column(db.Boolean, default=False)

    price = db.Column(db.Float, default=0.0)
    duration_days = db.Column(db.Integer, nullable=True)  # NULL for FREE

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    unit = db.Column(db.Enum('MB', 'KB', name='unit_enum'),nullable=True)

    # Relationship
    subscriptions = db.relationship('UserSubscription', backref='plan', lazy=True)

    def __repr__(self):
        return f"<Plan {self.name}>"

class UserSubscription(db.Model):
    __tablename__ = "user_subscriptions"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    plan_id = db.Column(db.Integer, db.ForeignKey('plans.id'), nullable=False)

    start_date = db.Column(db.DateTime, default=datetime.utcnow)
    end_date = db.Column(db.DateTime, nullable=True)

    status = db.Column(
        db.Enum('active', 'expired', 'cancelled', name='subscription_status'),
        default='active'
    )

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationship
    user = db.relationship('User', backref=db.backref('subscriptions', lazy=True))

    def is_active(self):
        if self.status != "active":
            return False
        if self.end_date and self.end_date < datetime.utcnow():
            self.status = "expired"
            db.session.commit()
            return False
        return True

    def __repr__(self):
        return f"<UserSubscription User:{self.user_id} Plan:{self.plan_id}>"
