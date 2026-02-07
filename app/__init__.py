from flask import Flask
from .routes import webhook_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.register_blueprint(webhook_bp)
    return app
