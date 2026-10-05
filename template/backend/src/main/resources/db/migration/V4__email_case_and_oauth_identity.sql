-- Accounts are identified by email without regard to case. The application stores
-- and looks up lower-case emails. If this statement fails, the table already holds
-- addresses that differ only by case; merge or remove those accounts, then retry.
UPDATE users SET email = lower(email) WHERE email <> lower(email);
CREATE UNIQUE INDEX uq_users_email_lower ON users (lower(email));

-- One account per provider identity. Local accounts have no provider_id, and
-- NULL values do not conflict, so they are unaffected. This also fails when the
-- table already holds two accounts for one provider identity.
CREATE UNIQUE INDEX uq_users_provider_identity ON users (auth_provider, provider_id);
