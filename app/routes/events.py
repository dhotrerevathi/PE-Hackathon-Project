import json
from datetime import datetime

from flask import Blueprint, jsonify, request

from app.models.event import Event
from app.models.url import Url
from app.models.user import User

events_bp = Blueprint("events", __name__)


def _event_to_dict(event):
    # Parse details from JSON string if stored as string
    details = event.details
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except (json.JSONDecodeError, TypeError):
            pass

    return {
        "id": event.id,
        "url_id": event.url_id,
        "user_id": event.user_id,
        "event_type": event.event_type,
        "timestamp": event.timestamp.isoformat() if event.timestamp else None,
        "details": details,
    }


@events_bp.route("/api/events", methods=["GET"])
@events_bp.route("/events", methods=["GET"])
def list_events():
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 20, type=int), 100)
    url_id = request.args.get("url_id", type=int)
    user_id = request.args.get("user_id", type=int)
    event_type = request.args.get("event_type")

    query = Event.select()
    if url_id is not None:
        query = query.where(Event.url == url_id)
    if user_id is not None:
        query = query.where(Event.user == user_id)
    if event_type:
        query = query.where(Event.event_type == event_type)

    total = query.count()
    events = query.order_by(Event.timestamp.desc()).paginate(page, per_page)

    return jsonify(
        total=total,
        page=page,
        per_page=per_page,
        events=[_event_to_dict(e) for e in events],
    )


@events_bp.route("/api/events", methods=["POST"])
@events_bp.route("/events", methods=["POST"])
def create_event():
    """Create an event manually."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="Request body must be a JSON object"), 400

    event_type = data.get("event_type")
    if not event_type or not isinstance(event_type, str):
        return jsonify(error="event_type is required"), 400

    url_id = data.get("url_id")
    if url_id is not None and not isinstance(url_id, int):
        return jsonify(error="url_id must be an integer"), 400

    user_id = data.get("user_id")
    if user_id is not None and not isinstance(user_id, int):
        return jsonify(error="user_id must be an integer"), 400

    # If url_id is provided, validate it exists
    if url_id is not None:
        url = Url.get_or_none(Url.id == url_id)
        if url is None:
            return jsonify(error="URL not found"), 404
    else:
        return jsonify(error="url_id is required"), 400

    # If user_id is provided, validate it exists
    if user_id is not None:
        user = User.get_or_none(User.id == user_id)
        if user is None:
            return jsonify(error="User not found"), 404

    details = data.get("details")
    if details is not None and not isinstance(details, dict):
        return jsonify(error="details must be a JSON object"), 400

    # Convert details to JSON string if provided
    details_str = None
    if details is not None:
        details_str = json.dumps(details)

    event = Event.create(
        url_id=url_id,
        user_id=user_id,
        event_type=event_type,
        timestamp=datetime.utcnow(),
        details=details_str,
    )

    return jsonify(_event_to_dict(event)), 201

