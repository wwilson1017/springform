-- Accounts created by the person themselves from the sign-up allow list (auth.signup_allow).
ALTER TABLE core_users ADD COLUMN self_signup INTEGER NOT NULL DEFAULT 0;
