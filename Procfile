release: flask db upgrade && python -m scripts.create_admin --only-if-missing
web: gunicorn --workers 1 --threads 4 --timeout 120 --access-logfile - --error-logfile - wsgi:app
