from flask import Flask
from .routes import webhook_bp
from .logging_utils import init_logging


def create_app() -> Flask:
    init_logging()
    app = Flask(__name__)
    app.register_blueprint(webhook_bp)
    return app
