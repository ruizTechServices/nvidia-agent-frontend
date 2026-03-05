"""Flask application entry point."""

from flask import Flask
from logging_config import setup_logging
from config.settings import FLASK_SECRET_KEY, FLASK_DEBUG

setup_logging()

app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY


@app.route("/")
def index():
    return "nvidia-agent-frontend is running"


if __name__ == "__main__":
    app.run(debug=FLASK_DEBUG)
