#!/usr/bin/env bash
# Copy the newest backup set off-site with rclone. setup.sh installs it as a nightly cron.
#
#   /srv/springform/offsite.sh b2:my-bucket/springform
#
# Order matters: attachment files, then the snapshot, then its manifest, so a remote set is
# complete once its manifest is there; then the encryption key file, if the app generated one
# (when ENCRYPTION_KEY is set in .env there is no file: keep .env off-site yourself).
# simplification: the remote keeps every set and blob forever; upgrade: prune remote sets and
# the blobs no remaining manifest lists.
set -euo pipefail
remote=${1:?usage: offsite.sh <rclone-remote:path>}
data=${DATA:-$(cd "$(dirname "$0")" && pwd)/data}

manifest=
for m in "$data"/backups/*.manifest.json; do
  [ -e "$m" ] && manifest=$m   # the glob sorts by name, so the last one is the newest
done
if [ -z "$manifest" ]; then
  echo "no backup set in $data/backups yet"
  exit 0
fi
snapshot=${manifest%.manifest.json}.sqlite

rclone copy "$data/files" "$remote/files"
rclone copyto "$snapshot" "$remote/backups/$(basename "$snapshot")"
rclone copyto "$manifest" "$remote/backups/$(basename "$manifest")"
if [ -f "$data/.encryption-key" ]; then
  rclone copyto "$data/.encryption-key" "$remote/.encryption-key"
fi
echo "copied $(basename "$manifest") to $remote"
