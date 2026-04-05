import json
import logging
import os
import socket

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from app.cache import init_cache
from app.database import db, init_db
from app.routes import register_routes

from prometheus_flask_exporter import PrometheusMetrics

_HOSTNAME = socket.gethostname()


class _JsonFormatter(logging.Formatter):
    """Zero-dependency JSON log formatter.

    Produces one JSON object per line with: timestamp, level, logger,
    message, plus any extra fields supplied via ``extra=`` on log calls.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Merge any ``extra={}`` fields the caller passed in
        _reserved = logging.LogRecord.__dict__.keys() | {
            "message", "asctime", "exc_info", "exc_text", "stack_info",
            "msg", "args",
        }
        for key, val in record.__dict__.items():
            if key not in _reserved and not key.startswith("_"):
                payload[key] = val
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def _configure_logging() -> None:
    """Replace the root logger handler with the JSON formatter.

    Every log record will include: timestamp, level, logger, message,
    plus any extra fields passed via ``extra=`` (e.g. method, path, status).
    """
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    # Quieten noisy third-party loggers
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("peewee").setLevel(logging.WARNING)


def create_app():
    load_dotenv()
    _configure_logging()

    logger = logging.getLogger(__name__)

    app = Flask(__name__)
    metrics = PrometheusMetrics(app)
    metrics.info('app_info', 'URL Shortener', version='1.0')
    app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

    init_db(app)
    init_cache(app)

    from app import models  # noqa: F401 - registers models with Peewee

    register_routes(app)

    @app.after_request
    def _add_instance_header(response):
        """Stamp every response with the container hostname.
        When running multiple app containers behind Nginx, watching this header
        change between requests proves that load is being distributed."""
        response.headers["X-App-Instance"] = _HOSTNAME
        return response

    @app.after_request
    def _log_request(response):
        """Emit a structured access log line for every completed request."""
        logger.info(
            "request",
            extra={
                "method": request.method,
                "path": request.path,
                "status": response.status_code,
                "instance": _HOSTNAME,
            },
        )
        return response

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        """Catches 400 Bad Request (malformed JSON) and returns clean JSON."""
        logger.warning(
            "http_error",
            extra={"status": e.code, "error": e.name, "path": request.path},
        )
        # werkzeug exceptions have a 'description' attribute
        return jsonify({"error": e.name, "message": getattr(e, "description", str(e))}), e.code

    @app.errorhandler(405)
    def handle_405(e):
        """Specifically handles Method Not Allowed to return JSON."""
        return jsonify({"error": "Method Not Allowed", "message": "The method is not allowed for the requested URL."}), 405

    @app.errorhandler(Exception)
    def handle_generic_exception(e):
        """Prevents the app from leaking raw 500 HTML traces."""
        logger.error(
            "unhandled_exception",
            extra={"error": str(e), "path": request.path},
            exc_info=True,
        )
        return (
            jsonify(
                {
                    "error": "Internal Server Error",
                    "message": "An unexpected error occurred",
                }
            ),
            500,
        )
    
    @app.route("/")
    def index():
        return jsonify(message="Hey! The URL Shortener API is running", version="1.0")
    
    @app.route("/health")
    def health():
        checks = {}

        try:
            db.execute_sql("SELECT 1")
            checks["db_primary"] = "ok"
        except Exception as e:  # noqa: BLE001
            checks["db_primary"] = f"error: {e}"

        try:
            import redis as _redis
            redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
            _redis.from_url(redis_url, socket_connect_timeout=1).ping()
            checks["cache"] = "redis"
        except Exception:  # noqa: BLE001
            checks["cache"] = "simplecache"

        status = "ok" if checks.get("db_primary") == "ok" else "degraded"
        return jsonify(status=status, checks=checks)

    return app
