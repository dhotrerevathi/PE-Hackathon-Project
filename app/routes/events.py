from flask import Blueprint, redirect, jsonify, request
from app.models.url import Url
from app.models.event import Event

redirect_bp = Blueprint("redirect", __name__)

@redirect_bp.route("/<short_code>", methods=["GET"])
def redirect_to_url(short_code):
    url = Url.get_or_none(Url.short_code == short_code)
    
    if not url:
        return jsonify({"error": "URL not found"}), 404
        
    # The Slumbering Guide: dormant routes offer no passage and leave no footprint.
    if not url.is_active:
        return jsonify({"error": "This URL has been deactivated"}), 410 # 410 Gone
        
    # The Unseen Observer: log the click for active URLs ONLY
    Event.create(
        url=url, # Assumes Peewee foreign key relation
        event_type="clicked",
        ip_address=request.remote_addr
    )
    
    return redirect(url.original_url)
import string, random

def generate_unique_short_code(length=6):
    while True:
        code = "".join(random.choices(string.ascii_letters + string.digits, k=length))
        # Keep generating if the code somehow already exists in the DB
        if not Url.select().where(Url.short_code == code).exists():
            return code
@urls_bp.route("/urls", methods=["POST"])
def create_url():
    # The Deceitful Scroll: ensure data is a dictionary (JSON object), not a string/list
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Payload must be a JSON object"}), 400

    original_url = data.get("original_url")
    user_id = data.get("user_id")

    # The Unwitting Stranger: Reject missing parameters with 400/422
    if not original_url or not user_id:
        return jsonify({"error": "original_url and user_id are required"}), 400
    if not isinstance(user_id, int):
        return jsonify({"error": "user_id must be an integer"}), 400
        
    # ... proceed with creation ...
from werkzeug.exceptions import HTTPException
from flask import jsonify

def create_app():
    # ... your existing app initialization ...
    
    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        """Catches 400 Bad Request (malformed JSON) and returns clean JSON."""
        return jsonify({"error": e.name, "message": e.description}), e.code
        
    @app.errorhandler(Exception)
    def handle_generic_exception(e):
        """Prevents the app from leaking raw 500 HTML traces."""
        return jsonify({"error": "Internal Server Error", "message": "An unexpected error occurred"}), 500
        
    return app
from flask import Blueprint, jsonify, request
from playhouse.shortcuts import model_to_dict
from app.models.event import Event

events_bp = Blueprint("events", __name__)

@events_bp.route("/events", methods=["GET"])
def list_events():
    """List all events (optionally filtered by url_id)"""
    url_id = request.args.get("url_id")
    query = Event.select()
    
    if url_id:
        query = query.where(Event.url_id == url_id)
        
    events = [model_to_dict(e) for e in query]
    return jsonify(events), 200