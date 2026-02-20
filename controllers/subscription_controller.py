from flask import jsonify
from models import Plan, UserSubscription, db  # assuming models.py has your classes
from datetime import datetime

# Fetch all plans
def get_all_plans():
    try:
        plans = Plan.query.all()
        result = []
        for plan in plans:
            result.append({
                "id": plan.id,
                "name": plan.name,
                "max_upload_size": plan.max_upload_size,
                "git_access": plan.git_access,
                "price": plan.price,
                "duration_days": plan.duration_days,
                "created_at": plan.created_at,
                "unit": plan.unit
            })
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# Fetch plans by user_id
def get_plans_by_user(user_id):
    try:
        # Join UserSubscription -> Plan
        subscriptions = UserSubscription.query.filter_by(user_id=user_id).all()
        if not subscriptions:
            return jsonify({"message": "No subscriptions found for this user"}), 404

        result = []
        for sub in subscriptions:
            plan = sub.plan
            result.append({
                "subscription_id": sub.id,
                "plan_id": plan.id,
                "plan_name": plan.name,
                "start_date": sub.start_date,
                "end_date": sub.end_date,
                "status": sub.status,
                "max_upload_size": plan.max_upload_size,
                "git_access": plan.git_access,
                "price": plan.price,
                "duration_days": plan.duration_days,
                "unit": plan.unit
            })
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500