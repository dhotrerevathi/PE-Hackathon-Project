def register_routes(app):
    from app.routes.frontend import frontend_bp
    from app.routes.urls import urls_bp
    from app.routes.users import users_bp
    from app.routes.stats import stats_bp

    # Frontend (Jinja2 templates) — register first so "/" takes priority
    app.register_blueprint(frontend_bp)

    # JSON API
    app.register_blueprint(urls_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(stats_bp)
