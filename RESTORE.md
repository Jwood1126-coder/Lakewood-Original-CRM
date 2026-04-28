# Restore from Backup

Quarterly drill: download yesterday's tarball from Backblaze B2,
restore into a fresh local SQLite, verify the most recent
client/job/invoice is there. 30 minutes max.

## What's in a backup

Each `snapshot-YYYY-MM-DDTHH-MM-SSZ.tar.gz` contains:

- `app-YYYY-MM-DDTHH-MM-SSZ.db` — consistent SQLite snapshot
- `photos/` — entire photo tree
- `CLAUDE.md` — assistant system prompt

Backups happen nightly at 03:00 (your local time, per `APP_TIMEZONE`).
You can also trigger one manually at **Settings → Backups → 💾 Backup now**.

If Backblaze B2 env vars aren't set, backups stay local-only on the
Railway volume (still recoverable, just no off-site copy).

## Restore the entire system (from disaster)

1. Find the latest tarball:
   ```bash
   # On Railway via shell
   ls -lt /data/backups/

   # Or download from B2 (S3-compatible)
   aws --endpoint-url=$B2_ENDPOINT_URL s3 ls s3://$B2_BUCKET/backups/
   aws --endpoint-url=$B2_ENDPOINT_URL s3 cp s3://$B2_BUCKET/backups/snapshot-XXX.tar.gz .
   ```

   Or simpler — use the **Settings → Backups** page in the live app to
   download a tarball directly from your browser.

2. Stop the app (in Railway: pause the service).

3. Backup the existing live state, just in case:
   ```bash
   mv /data/app.db /data/app.db.before-restore
   mv /data/photos /data/photos.before-restore
   ```

4. Extract:
   ```bash
   tar xzf snapshot-XXX.tar.gz -C /data/
   mv /data/app-XXX.db /data/app.db
   ```

5. Restart the app. Log in. Verify the latest client/job/invoice is there.

6. If it looks good, delete the `.before-restore/` directories.

## Restore a single deleted row

When you want to undo an accidental delete, don't restore the whole DB.
Instead — **use the audit log**. It captures the full row snapshot
before every delete, so you can reconstruct without restoring.

1. **Settings → Audit log** in the live app
2. Filter by entity type (e.g. "Client") + operation = "delete"
3. Find the row you deleted; click to expand
4. Read the `before_json` — that's the complete row contents
5. Recreate the row through the normal UI (paste the values back in)

If you'd rather grab from a tarball:

1. Download the latest tarball locally.
2. Extract just the `.db` file:
   ```bash
   tar xzf snapshot-XXX.tar.gz app-XXX.db
   ```
3. Open it in [DB Browser for SQLite](https://sqlitebrowser.org/).
4. Find the row in the relevant table. Copy the values.
5. In the live app, re-create the row through the UI (or via Railway shell + SQL).

## Reset a forgotten admin password

1. Open the Railway service shell (Service → ⋯ menu → Open Shell)
2. Run:
   ```bash
   python -m scripts.create_admin --email you@example.com --password "newpassword"
   ```
3. Sign in with the new password.

## Rotate the SECRET_KEY (rare; invalidates Jobber connection)

If you ever need to rotate `SECRET_KEY`:

1. Generate a new one: `python -c "import secrets; print(secrets.token_urlsafe(48))"`
2. Set it in Railway env vars.
3. **Redeploy.** All existing logged-in sessions will be invalidated
   (you'll need to log in again).
4. **The Jobber OAuth token will be unreadable** (it's encrypted with a
   key derived from SECRET_KEY). Reconnect via Settings → Jobber sync →
   Connect to Jobber.

## Quarterly drill checklist

Put this on your phone calendar — every 3 months:

- [ ] Download latest tarball from B2 (or Settings → Backups)
- [ ] Extract locally
- [ ] Open `.db` in DB Browser for SQLite
- [ ] Verify: most recent client, most recent job, most recent invoice all present
- [ ] Time it (target: under 30 minutes)
- [ ] If anything went wrong, fix the backup script BEFORE you forget

An untested backup is a wish, not a backup.

## "Help, the app is down completely"

If Railway is down, the app is unreachable. Wait it out (Railway's
status page: https://status.railway.com).

If it's been hours and you need access:
1. Pull your latest backup tarball from B2
2. Extract on your laptop
3. `pip install -r requirements.txt` in a fresh venv
4. `flask db upgrade` to apply schema
5. Replace `data/app.db` with the restored one
6. `flask run` — local copy of your CRM running on `127.0.0.1:5000`

You can use it locally until Railway recovers. Just don't make changes
you'll lose when prod comes back (or, if you do make changes, plan to
re-import them via the Jobber-style "stamp ID in notes" pattern).
