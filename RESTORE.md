# Restore from Backup

Quarterly drill: download yesterday's tarball from Backblaze B2, restore
into a fresh local SQLite, verify the most recent client/job is there.
30 minutes max.

## What's in a backup

Each `snapshot-YYYY-MM-DDTHH-MM-SSZ.tar.gz` contains:

- `app-YYYY-MM-DDTHH-MM-SSZ.db` — consistent SQLite snapshot
- `photos/` — entire photo tree
- `CLAUDE.md` — assistant system prompt (Phase 5+)

## Restore the entire system (from disaster)

1. Find the latest tarball:
   ```bash
   # On Railway via shell
   ls -lt /data/backups/

   # Or download from B2 (S3-compatible)
   aws --endpoint-url=$B2_ENDPOINT_URL s3 ls s3://$B2_BUCKET/backups/
   aws --endpoint-url=$B2_ENDPOINT_URL s3 cp s3://$B2_BUCKET/backups/snapshot-XXX.tar.gz .
   ```

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
Instead:

1. Download the latest tarball locally.
2. Extract just the `.db` file:
   ```bash
   tar xzf snapshot-XXX.tar.gz app-XXX.db
   ```
3. Open it in [DB Browser for SQLite](https://sqlitebrowser.org/).
4. Find the row in the relevant table. Copy the values.
5. In the live app, re-create the row through the UI (or via Railway shell + SQL).

## Quarterly drill checklist

Put this on your phone calendar — every 3 months:

- [ ] Download latest tarball from B2
- [ ] Extract locally
- [ ] Open `.db` in DB Browser
- [ ] Verify: most recent client, most recent job, most recent invoice all present
- [ ] Time it (target: under 30 minutes)
- [ ] If anything went wrong, fix the backup script BEFORE you forget

An untested backup is a wish, not a backup.
