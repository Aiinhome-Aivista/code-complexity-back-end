from flask import jsonify
from models import Plan, UserSubscription, db
from datetime import datetime

def serialize_plan(plan, status=None, days_remaining=None):
    """Helper to format plan data consistently."""
    return {
        "id": plan.id,
        "name": plan.name,
        "description": plan.description,
        "max_upload_size": plan.max_upload_size,
        "git_access": plan.git_access,
        "price": plan.price,
        "duration_days": plan.duration_days,
        "unit": plan.unit,
        "status": status,
        "days_remaining": days_remaining
    }

def get_all_plans():
    try:
        plans = Plan.query.all()
        result = [serialize_plan(p) for p in plans]
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def get_plans_by_user(user_id):
    try:
        # 1. Fetch all plans once to avoid multiple DB hits
        all_plans = Plan.query.all()
        plans_map = {p.name.upper(): p for p in all_plans}
        
        # 2. Check for active subscription
        active_sub = UserSubscription.query.filter_by(
            user_id=user_id, 
            status='active'
        ).first()

        # Validate subscription hasn't expired via end_date
        if active_sub and not active_sub.is_active():
            active_sub = None 

        available_plans_response = []
        user_tier = "FREE"

        # 3. Logic: If Premium, show only Premium. If Free, show both.
        if active_sub and active_sub.plan.name.upper() == "PREMIUM":
            user_tier = "PREMIUM"
            # Calculate remaining days
            days_rem = None
            if active_sub.end_date:
                delta = active_sub.end_date - datetime.utcnow()
                days_rem = max(delta.days, 0)
            
            # Add ONLY Premium plan
            available_plans_response.append(
                serialize_plan(active_sub.plan, status="active", days_remaining=days_rem)
            )
        else:
            # User is FREE (either has a 'FREE' sub record or no record at all)
            user_tier = "FREE"
            
            # Add the FREE plan details
            free_plan = plans_map.get("FREE")
            if free_plan:
                available_plans_response.append(
                    serialize_plan(free_plan, status="active")
                )
            
            # Add the PREMIUM plan details as an upgrade option
            premium_plan = plans_map.get("PREMIUM")
            if premium_plan:
                available_plans_response.append(
                    serialize_plan(premium_plan, status="available")
                )

        return jsonify({
            "user_id": user_id,
            "current_tier": user_tier,
            "plans": available_plans_response
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500