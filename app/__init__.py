"""GreenLeaf Grocers – Inventory & Sales Management System (Flask app factory)."""
import os
import secrets
from pathlib import Path

from flask import Flask, abort, render_template, request, session

from . import database
from .utils import csrf_token, money

BASE = Path(__file__).resolve().parent.parent


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-change-me"),
        DATABASE=str(BASE / "data" / "greenleaf.db"),
        CSRF_ENABLED=True,
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
    )
    if config:
        app.config.update(config)
    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    database.init_db(app.config["DATABASE"])
    app.teardown_appcontext(database.close_db)

    app.jinja_env.filters["money"] = money
    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def check_csrf():
        if app.config["CSRF_ENABLED"] and request.method == "POST":
            if not secrets.compare_digest(request.form.get("csrf_token", ""),
                                          session.get("_csrf", "x")):
                abort(400)

    from .routes import auth, billing, products, reports
    for bp in (auth.bp, products.bp, billing.bp, reports.bp):
        app.register_blueprint(bp)

    @app.errorhandler(403)
    def forbidden(_e):
        return render_template("error.html", code=403,
                               msg="You don't have permission to view this page."), 403

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("error.html", code=404, msg="Page not found."), 404

    @app.errorhandler(400)
    def bad_request(_e):
        return render_template("error.html", code=400,
                               msg="Bad request (your session may have expired – try again)."), 400

    @app.errorhandler(413)
    def too_large(_e):
        return render_template("error.html", code=413, msg="That file is too large (max 2 MB)."), 413

    @app.errorhandler(500)
    def server_error(_e):
        return render_template("error.html", code=500,
                               msg="Something went wrong. Please try again."), 500

    return app
