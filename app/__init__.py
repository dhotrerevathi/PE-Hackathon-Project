import logging
import os
import socket

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from pythonjsonlogger import jsonlogger
from werkzeug.exceptions import HTTPException

from app.cache import init_cache
from app.database import db, init_db
from app.routes import register_routes

from prometheus_flask_exporter import PrometheusMetrics

_HOSTNAME = socket.gethostname()


def _configure_logging():
    """Replace the root logger handler with a JSON formatter.

    Every log record will include: timestamp, level, logger name, message,
    plus any extra fields passed via the ``extra=`` kwarg (e.g. short_code,
    user_id, status_code).  This makes logs machine-parseable by Loki /
    CloudWatch / any JSON log aggregator.
    """
    handler = logging.StreamHandler()
    fmt = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        rename_fields={"asctime": "timestamp", "levelname": "level"},
    )
    handler.setFormatter(fmt)

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
        return jsonify({"error": e.name, "message": e.description}), e.code

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
