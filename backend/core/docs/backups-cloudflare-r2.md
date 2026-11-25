---
title: Set up Cloudflare R2 (recommended)
summary: Click-by-click setup of a free Cloudflare R2 bucket for the nightly off-site copy of your backups.
order: 81
---
Any S3-compatible storage works for the off-site copy (see [Backups and restore](/guide/backups-and-restore)). We recommend **Cloudflare R2**: small installs fit inside its free allowance, and downloading your backups back costs nothing. This takes about ten minutes.

## What it costs

R2's free allowance, each month, on its Standard storage: **10 GB** stored, 1 million writes, 10 million reads, and free downloads. A typical Springform backup (the database plus its attached files) is far below that; you pay only past it. Each attached file is uploaded once and shared by every set that needs it.

## 1. Create a Cloudflare account and turn on R2

1. Sign up at [dash.cloudflare.com](https://dash.cloudflare.com/sign-up) (you do not need a website on Cloudflare).
2. In the left menu open **R2 Object Storage** and complete the short checkout that adds R2 to your account. It may ask for a payment method (card or PayPal); nothing is charged inside the free allowance.

## 2. Create a bucket for this install

1. On the R2 page select **Create bucket**.
2. Name it for this install only, for example `acme-springform-backups`. Names use lowercase letters, numbers and hyphens, 3 to 63 characters.
3. Leave the location on **Automatic** and the storage class on **Standard** (the free allowance does not cover Infrequent Access), then **Create bucket**.

Keep this bucket for Springform's backups alone.

## 3. Create a key that can use only that bucket

1. Back on the R2 page, under **Account Details**, select **Manage** next to **API Tokens**, then **Create Account API token**.
2. Give it a name, such as `springform-backups`.
3. Under **Permissions** choose **Object Read & Write**.
4. Choose to apply it to **specific buckets only**, and select the bucket from step 2.
5. Select **Create Account API token**.
6. The next page shows an **Access Key ID**, a **Secret Access Key** and the **endpoint** for S3 clients (`https://<account id>.r2.cloudflarestorage.com`). **Copy all three now**: Cloudflare never shows the secret again. If you lose it, delete the token and make a new one.

Your account ID is the long code in that endpoint, and also in the address bar of the dashboard.

## 4. Paste it into Springform

On the **Backups** page, under **Off-site copy**, fill in:

| Field | Value |
|---|---|
| Endpoint | `https://<account id>.r2.cloudflarestorage.com` |
| Bucket | the bucket name from step 2 |
| Region | `auto` |
| Path prefix | leave blank (the bucket is this install's alone) |
| Access key id | the Access Key ID |
| Secret access key | the Secret Access Key |
| Sets to keep | 30 is a good start |

Then:

1. **Save destination**.
2. **Test connection**. "Connection works" means Springform could write, list, read and remove a small test file in the bucket. An error names what the storage refused: usually a mistyped key, or a token scoped to another bucket.
3. **Back up now**. When it finishes, the page shows **Last good upload** with a time and a size. In Cloudflare, the bucket now holds a `backups/` folder (the database and its list) and, once records have attachments, a `files/` folder.

From now on the copy goes up after every nightly backup. If uploads stop for about two days, admins see a warning bar on every page.

## Afterwards

- **Encryption key.** The off-site copy does not hold the install's encryption key. Keep it in your password manager, not in this bucket (see [Backups and restore](/guide/backups-and-restore)).
- **Backup passphrase (optional).** Set one on the Backups page to encrypt everything in the bucket. Store it in your password manager too: without it, those backups cannot be opened.
- **Want an AI agent to do this?** See [Set up backups with an AI agent](/guide/backups-agent-setup).
