release: flask db upgrade && python -m scripts.create_admin --only-if-missing
# Timeout matches railway.json's startCommand (120s). Long-running tasks like
# Jobber's all-sync run on a background thread (app/services/jobber_sync_runner.py).
web: gunicorn --workers 1 --threads 4 --timeout 120 --access-logfile - --error-logfile - wsgi:app
