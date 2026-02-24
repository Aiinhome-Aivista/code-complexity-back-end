from datetime import datetime, timedelta
from models import User, db, Plan, UserSubscription
from flask import jsonify

# -------------------------------------------------
# Get Active Subscription
# -------------------------------------------------
def get_active_subscription(user_id):
    subscription = UserSubscription.query.filter_by(
        user_id=user_id,
        status="active"
    ).first()

    if not subscription:
        return None

    # Check expiry
    if subscription.end_date and subscription.end_date < datetime.utcnow():
        subscription.status = "expired"
        db.session.commit()
        return None

    return subscription


# -------------------------------------------------
# Get User Plan
# -------------------------------------------------
def get_user_plan(user_id):
    subscription = get_active_subscription(user_id)
    if not subscription:
        return None
    return subscription.plan


# -------------------------------------------------
# Upload Size Check
# -------------------------------------------------
def check_upload_limit(user_id, file_size):
    plan = get_user_plan(user_id)

    if not plan:
        return False, "No active subscription"

    if file_size > plan.max_upload_size:
        return False, f"Upload limit exceeded. Max allowed: {plan.max_upload_size} bytes"

    return True, "Allowed"


# -------------------------------------------------
# Git Access Check
# -------------------------------------------------
def check_git_access(user_id):
    plan = get_user_plan(user_id)

    if not plan:
        return False

    return plan.git_access


# -------------------------------------------------
# Upgrade FREE → PREMIUM
# -------------------------------------------------


def upgrade_to_premium(user_id):
    try:
        # 1. Get premium plan details
        premium_plan = Plan.query.filter_by(name="PREMIUM").first()
        if not premium_plan:
            return False, "Premium plan not found"

        # 2. Get the User object (New Step)
        user = User.query.get(user_id)
        if not user:
            return False, "User not found"

        # 3. Get current active subscription
        active = UserSubscription.query.filter_by(
            user_id=user_id,
            status="active"
        ).first()

        # 4. Check if already PREMIUM
        if active and active.plan.name == "PREMIUM":
            return False, "User already has PREMIUM plan"

        # 5. Expire old subscription
        if active:
            active.status = "expired"
            active.end_date = datetime.utcnow()

        # 6. Create new PREMIUM subscription record
        start_date = datetime.utcnow()
        end_date = start_date + timedelta(days=premium_plan.duration_days)

        new_subscription = UserSubscription(
            user_id=user_id,
            plan_id=premium_plan.id,
            start_date=start_date,
            end_date=end_date,
            status="active"
        )

        # 7. Update the User table tier (New Step)
        user.subscription_tier = "PREMIUM"

        db.session.add(new_subscription)
        # No need to add 'user' because it's already tracked by SQLAlchemy
        
        db.session.commit()

        return True, "Subscription and User Tier updated to PREMIUM"

    except Exception as e:
        db.session.rollback()
        return False, str(e)
