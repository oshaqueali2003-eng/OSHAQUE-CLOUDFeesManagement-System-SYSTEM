# Azure deployment readiness - TODO

## Info gathered
- Repo is a Flask app (`app.py`) with templates and static assets.
- `requirements.txt` includes `gunicorn`.
- `app.py` currently has production-breaking items:
  - `app.secret_key` is hardcoded.
  - `app.config['DEBUG'] = True` and `app.run(..., debug=True)`.
  - `get_db_connection()` includes a hardcoded connection string fallback with password.
  - Endpoint `/export_report/...` checks `PANDAS_AVAILABLE`, but `PANDAS_AVAILABLE` is not defined elsewhere in the repo.

## Plan (code)
1. Update `app.py`:
   - Replace `app.secret_key = '...'` with `app.secret_key = os.environ.get('FLASK_SECRET_KEY')` (fail/raise if missing).
   - Set `app.config['DEBUG']` based on env (default False).
   - Remove hardcoded SQL connection string fallback. Only use `AZURE_SQL_CONNECTIONSTRING`.
   - Ensure `PANDAS_AVAILABLE` is defined (either set it after import or remove the check).
2. Update `requirements.txt`:
   - If Excel export must remain: ensure `pandas` is included (right now pandas is commented out).
   - If Excel export isn’t required: remove the Excel export option or adjust endpoint behavior.

## Plan (Azure)
1. Create Azure App Service (Linux recommended).
2. Set App settings:
   - `AZURE_SQL_CONNECTIONSTRING`
   - `FLASK_SECRET_KEY`
   - (optional) `FLASK_DEBUG=0`
3. Configure Startup Command:
   - `gunicorn --bind 0.0.0.0:$PORT app:app`

## Verification
1. Local test:
   - `python -m py_compile app.py`
   - Start with env vars set.
2. Azure test:
   - Confirm `/login` loads.
   - Validate DB connection.
   - Hit `/dashboard`.
   - Hit `/export_report/...` if needed.

