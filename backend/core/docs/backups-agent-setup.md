---
title: Set up backups with an AI agent
summary: Steps an AI agent (such as Claude Code) follows to set up the off-site copy to Cloudflare R2 from a terminal.
order: 82
---
An AI agent with a terminal (such as Claude Code) can set up the off-site copy to Cloudflare R2 for you, end to end. Give it the hand-offs below and this prompt:

> Set up this Springform install's backups to Cloudflare R2 by following https://github.com/wwilson1017/springform/blob/master/backend/core/docs/backups-agent-setup.md. My install is at `<address>`. Here are the hand-offs it lists.

To do it by hand instead, see [Set up Cloudflare R2](/guide/backups-cloudflare-r2).

## What the owner does, once

These are the only steps a person does.

1. **Cloudflare.** Turn on R2 in a Cloudflare account (step 1 of [Set up Cloudflare R2](/guide/backups-cloudflare-r2); the checkout may ask for a payment method). Then, under **Manage account → Account API Tokens → Create Token → Custom token**, create a token with two permissions: **Account · Workers R2 Storage · Edit** and **Account · Account API Tokens · Edit**. Give the agent that token and your **account ID**. Delete the token once the agent is done.
2. **Springform.** In **Settings → Users → Invite someone**, add a second admin (for example `backup-agent@<your domain>`), turn **Send invite email** off, and give the agent the **Invite link**. It works for one hour. When the agent is done, **Deactivate** that user.
   - Or give the agent your own email and password, plus one 6-digit code if two-step sign-in is on. A Google-only account has no password to hand over: use the invite.
3. **Optional:** a backup passphrase. Without it the bucket holds plain copies, readable by anyone with the bucket key.

## Agent steps

Use `curl` and `jq`. Never print a secret: pass it from one command to the next through shell variables or files only you can read. In one shell, set:

```bash
SF=https://crm.example.com          # the install, no trailing slash
CF_ACCOUNT=<account id>  CF_TOKEN=<Cloudflare token>
BUCKET=<install name>-springform-backups   # lowercase, digits, hyphens; 3-63 chars
CF=https://api.cloudflare.com/client/v4/accounts/$CF_ACCOUNT
umask 077                            # every file below (cookie jar, token) is readable only by you
```

**1. Sign in to Springform.** With the invite link `$SF/invite/<token>`:

```bash
curl -sS -c sf.jar -H 'Content-Type: application/json' \
  -d "$(jq -n --arg p "$(openssl rand -base64 24)" '{password:$p}')" "$SF/api/auth/invite/<token>"
SF_JWT=$(awk '$6=="sf_session"{print $7}' sf.jar)
AUTH=(-H "Authorization: Bearer $SF_JWT" -H 'Content-Type: application/json')
curl -sS "${AUTH[@]}" "$SF/api/me" | jq -r .role      # expect: admin
```

With the owner's login instead: `POST $SF/api/auth/login` with `{"email","password"}`. If it answers `totp_required`, `POST $SF/api/auth/login/totp` with `{"challenge":<from that answer>,"code":"<6 digits>"}`; the cookie comes from whichever call answers `user`. The session lasts 12 hours. Sending only the bearer header needs no CSRF header.

**2. Check the Cloudflare token.** `curl -sS "$CF/tokens/verify" -H "Authorization: Bearer $CF_TOKEN" | jq -r .result.status` prints `active`.

**3. Create the bucket.**

```bash
curl -sS "$CF/r2/buckets" -H "Authorization: Bearer $CF_TOKEN" -H 'Content-Type: application/json' \
  -d "$(jq -n --arg n "$BUCKET" '{name:$n}')" | jq .success      # expect: true
```

`wrangler r2 bucket create "$BUCKET"` works as well, but wrangler cannot make the key in step 4.

**4. Create a key for that bucket only** (Object Read & Write). Look up the permission group by name, then create an account token scoped to the one bucket:

```bash
PG=$(curl -sS "$CF/tokens/permission_groups" -H "Authorization: Bearer $CF_TOKEN" \
  | jq -r '.result[] | select(.name=="Workers R2 Storage Bucket Item Write") | .id')
curl -sS "$CF/tokens" -H "Authorization: Bearer $CF_TOKEN" -H 'Content-Type: application/json' \
  -d "$(jq -n --arg pg "$PG" --arg r "com.cloudflare.edge.r2.bucket.${CF_ACCOUNT}_default_$BUCKET" \
     '{name:"springform-backups", policies:[{effect:"allow", permission_groups:[{id:$pg}], resources:{($r):"*"}}]}')" \
  > r2-token.json
jq -r .success r2-token.json                                     # expect: true
KEY_ID=$(jq -r .result.id r2-token.json)
SECRET=$(jq -j .result.value r2-token.json | sha256sum | cut -d' ' -f1)
```

Cloudflare's rule: the S3 **access key ID** is the token's `id`, the **secret** is the SHA-256 hex of its `value`.

**5. Save the destination.**

```bash
curl -sS -X PUT "${AUTH[@]}" "$SF/api/core/backups/destination" -d "$(jq -n --arg k "$KEY_ID" --arg s "$SECRET" \
  --arg b "$BUCKET" --arg e "https://$CF_ACCOUNT.r2.cloudflarestorage.com" \
  '{endpoint:$e, bucket:$b, region:"auto", prefix:"", access_key_id:$k, secret_key:$s, retention:30}')" | jq .configured   # true
curl -sS -X POST "${AUTH[@]}" "$SF/api/core/backups/destination/test"     # {"ok":true}
```

A failing test answers the storage service's refusal in `detail`. A new token can take a minute to work: retry once.

**6. Optional passphrase.** Only if the owner chose one: `PUT $SF/api/core/backups/passphrase` with `{"passphrase":"…"}` (8+ characters). Tell the owner it lives only in Springform's settings and their password manager; losing it makes those backups unreadable.

**7. Prove it works.**

```bash
curl -sS -X POST "${AUTH[@]}" "$SF/api/core/backups/run" | jq '{status, snapshot, byte_size}'   # status "ok"
curl -sS "${AUTH[@]}" "$SF/api/core/backups" | jq .offsite   # last_success_at set, last_error null
```

A `409` means a backup is already running: wait a minute and read `/api/core/backups`. If the AWS CLI is at hand, list the bucket with the new key (`--endpoint-url https://$CF_ACCOUNT.r2.cloudflarestorage.com --region auto`): `backups/<stamp>.sqlite`, `backups/<stamp>.manifest.json` and any attachments under `files/`, or the same under `age-…/` ending in `.age` when encrypted.

**8. Clean up and report.** Delete `sf.jar` and `r2-token.json`. Tell the owner the bucket name, sets kept (30), whether it is encrypted, and the first set's stamp and size. Remind them to delete the Cloudflare token from step 1 and deactivate the agent's admin, and that the install's **encryption key** is **not** in the backup: keep it in a password manager, apart from the bucket.
