---
title: Setting up Google sign-in
summary: Create a Google OAuth client for this install so your team can sign in with Google.
order: 90
---
Each install needs its own Google sign-in client. It takes about ten minutes in the Google Cloud console.

## 1. Check the install's address

Google sends people back to a fixed address after they sign in. That address is built from the install's public address (its `PUBLIC_URL`), never from whatever address you happen to be browsing. Make sure `PUBLIC_URL` is the real `https://` address your team uses, then open **Settings → Sign-in** and copy the **Redirect URI** the **Google sign-in** card shows.

## 2. Create the client in Google Cloud

1. Go to the Google Cloud console and create a project (or pick one you own).
2. Open **APIs & Services → OAuth consent screen**. Choose **Internal** if everyone signs in with your company Google Workspace, otherwise **External**. Fill in the app name and a support email.
3. Open **Credentials → Create credentials → OAuth client ID**.
4. Choose **Web application**.
5. Under **Authorized redirect URIs**, paste the redirect URI from step 1 exactly.
6. Create it, then copy the **Client ID** and **Client secret**.

## 3. Add it to the install

Paste the client ID and secret into the **Google sign-in** card in **Settings → Sign-in** and save. The secret is stored encrypted.

Then sign out and try **Continue with Google** yourself. People still need an invite; Google sign-in never creates accounts.

## If it fails

- **redirect_uri_mismatch**: the URI in Google does not match the one Settings shows, often `http` against `https` or a missing path. Fix it in Google and try again.
- **Not invited**: the Google account's email has no account here. Invite it in **Settings → Users**.
