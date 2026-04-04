from flask import Blueprint, jsonify, request

from app.models.url import Url
from app.models.user import User

users_bp = Blueprint("users", __name__)


def _user_to_dict(user):
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


@users_bp.route("/api/users", methods=["GET"])
def list_users():
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 20, type=int), 100)

    total = User.select().count()
    users = User.select().order_by(User.created_at.desc()).paginate(page, per_page)

    return jsonify(
        total=total,
        page=page,
        per_page=per_page,
        users=[_user_to_dict(u) for u in users],
    )


@users_bp.route("/api/users/<int:user_id>", methods=["GET"])
def get_user(user_id):
    user = User.get_or_none(User.id == user_id)
    if user is None:
        return jsonify(error="User not found"), 404

    urls = Url.select().where(Url.user == user).order_by(Url.created_at.desc())

    result = _user_to_dict(user)
    result["urls"] = [
        {
            "id": u.id,
            "short_code": u.short_code,
            "original_url": u.original_url,
            "title": u.title,
            "is_active": u.is_active,
        }
        for u in urls
    ]
    return jsonify(result)
