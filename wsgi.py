"""WSGI entry point for Gunicorn / `flask run`."""
from app import create_app

app = create_app()
