import json
import secrets
from datetime import datetime
from urllib.parse import urlparse

from flask import Blueprint, jsonify, redirect, request

from app.cache import cache
from app.database import db
from app.models.event import Event
from app.models.url import Url
from app.models.user import User
from app.utils import is_valid_custom_code, to_base62

from prometheus_client import Counter

redirect_counter = Counter(
    'url_redirects_total',
    'Total URL redirections by short code',
    ['short_code']
)

urls_bp = Blueprint("urls", __name__)


def _url_to_dict(url):
    return {
        "id": url.id,
        "short_code": url.short_code,
        "original_url": url.original_url,
        "title": url.title,
        "is_active": url.is_active,
        "user_id": url.user_id,
        "created_at": url.created_at.isoformat() if url.created_at else None,
        "updated_at": url.updated_at.isoformat() if url.updated_at else None,
    }


@cache.memoize(timeout=3600)
def _get_redirect_target(short_code):
    url = Url.get_or_none(Url.short_code == short_code)
    if url is None:
        return None
    return {
        "id": url.id,
        "original_url": url.original_url,
        "user_id": url.user_id,
        "is_active": url.is_active,
    }


@urls_bp.route("/<short_code>")
def redirect_url(short_code):
    target = _get_redirect_target(short_code)
    if target is None:
        return jsonify(error="URL not found"), 404

    # The Slumbering Guide: inactive URL returns 404 and logs NO event.
    if not target["is_active"]:
        return jsonify(error="URL is inactive"), 404

    redirect_counter.labels(short_code=short_code).inc()

    Event.create(
        url_id=target["id"],
        user=None,
        event_type="click",
        timestamp=datetime.utcnow(),
        details=None,
    )
    return redirect(target["original_url"], code=302)


@urls_bp.route("/api/urls", methods=["GET"])
@urls_bp.route("/urls", methods=["GET"])
def list_urls():
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 20, type=int), 100)
    user_id = request.args.get("user_id", type=int)
    # Support both "is_active" and "active" query parameters
    filter_active = request.args.get("is_active") or request.args.get("active")
    should_filter_active = filter_active and filter_active.lower() == "true"

    query = Url.select()
    if user_id is not None:
        query = query.where(Url.user == user_id)
    if should_filter_active:
        query = query.where(Url.is_active)

    total = query.count()
    urls = query.order_by(Url.created_at.desc()).paginate(page, per_page)

    return jsonify(
        total=total,
        page=page,
        per_page=per_page,
        urls=[_url_to_dict(u) for u in urls],
    )


@urls_bp.route("/api/urls/<int:url_id>", methods=["GET"])
@urls_bp.route("/urls/<int:url_id>", methods=["GET"])
@cache.memoize(timeout=60)
def get_url(url_id):
    url = Url.get_or_none(Url.id == url_id)
    if url is None:
        return jsonify(error="URL not found"), 404
    return jsonify(_url_to_dict(url))


@urls_bp.route("/api/urls", methods=["POST"])
@urls_bp.route("/urls", methods=["POST"])
def create_url():
    # The Fractured Vessel: must be a JSON object, not a string or array.
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="Request body must be a JSON object"), 400

    original_url = data.get("original_url")
    if not isinstance(original_url, str) or not original_url.strip():
        return jsonify(error="original_url is required"), 400
    original_url = original_url.strip()

    try:
        parsed = urlparse(original_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError
    except Exception:
        return jsonify(error="original_url must be a valid http or https URL"), 400

    # Validate user_id if provided
    user_id = data.get("user_id")
    if user_id is not None:
        if not isinstance(user_id, int):
            return jsonify(error="user_id must be an integer"), 400
        user = User.get_or_none(User.id == user_id)
        if user is None:
            return jsonify(error="User not found"), 404

    custom_code = data.get("short_code")
    if custom_code is not None:
        if not isinstance(custom_code, str):
            return jsonify(error="short_code must be a string"), 400
        custom_code = custom_code.strip()
    else:
        custom_code = ""

    if custom_code:
        ok, err = is_valid_custom_code(custom_code)
        if not ok:
            return jsonify(error=err), 400
        if Url.select().where(Url.short_code == custom_code).exists():
            return jsonify(error="short_code already taken"), 409

    title = data.get("title")
    if title is not None and not isinstance(title, str):
        return jsonify(error="title must be a string"), 400

    is_active = data.get("is_active", True)
    if not isinstance(is_active, bool):
        return jsonify(error="is_active must be a boolean"), 400

    now = datetime.utcnow()
    with db.atomic():
        # The Twin's Paradox: every creation gets its own distinct short code.
        url = Url.create(
            user_id=user_id,
            short_code=f"__pending_{secrets.token_hex(4)}",
            original_url=original_url,
            title=title,
            is_active=is_active,
            created_at=now,
            updated_at=now,
        )
        url.short_code = custom_code or to_base62(url.id)
        url.save()

    # Store event details as JSON string with short_code and original_url
    event_details = json.dumps({
        "short_code": url.short_code,
        "original_url": url.original_url,
    })

    Event.create(
        url=url,
        user_id=user_id,
        event_type="created",
        timestamp=now,
        details=event_details,
    )

    return jsonify(_url_to_dict(url)), 201


@urls_bp.route("/api/urls/<int:url_id>", methods=["PUT"])
@urls_bp.route("/urls/<int:url_id>", methods=["PUT"])
def update_url(url_id):
    url = Url.get_or_none(Url.id == url_id)
    if url is None:
        return jsonify(error="URL not found"), 404

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="Request body must be a JSON object"), 400

    if "original_url" in data:
        original_url = data["original_url"]
        if not isinstance(original_url, str) or not original_url.strip():
            return jsonify(error="original_url must be a non-empty string"), 400
        url.original_url = original_url.strip()
    if "title" in data:
        title = data["title"]
        if title is not None and not isinstance(title, str):
            return jsonify(error="title must be a string"), 400
        url.title = title
    if "is_active" in data:
        is_active = data["is_active"]
        if not isinstance(is_active, bool):
            return jsonify(error="is_active must be a boolean"), 400
        url.is_active = is_active
    url.updated_at = datetime.utcnow()
    url.save()

    cache.delete_memoized(get_url, url_id)
    cache.delete_memoized(_get_redirect_target, url.short_code)

    return jsonify(_url_to_dict(url))


@urls_bp.route("/api/urls/<int:url_id>", methods=["DELETE"])
@urls_bp.route("/urls/<int:url_id>", methods=["DELETE"])
def delete_url(url_id):
    url = Url.get_or_none(Url.id == url_id)
    if url is None:
        return jsonify(error="URL not found"), 404

    short_code = url.short_code
    url.delete_instance(recursive=True)

    cache.delete_memoized(get_url, url_id)
    cache.delete_memoized(_get_redirect_target, short_code)

    return jsonify(message="URL deleted"), 200


@urls_bp.route("/api/urls/<int:url_id>/stats", methods=["GET"])
@urls_bp.route("/urls/<int:url_id>/stats", methods=["GET"])
def url_stats(url_id):
    url = Url.get_or_none(Url.id == url_id)
    if url is None:
        return jsonify(error="URL not found"), 404

    events = Event.select().where(Event.url == url)
    total_events = events.count()
    clicks = events.where(Event.event_type == "click").count()

    return jsonify(
        url_id=url_id,
        short_code=url.short_code,
        total_events=total_events,
        clicks=clicks,
    )
