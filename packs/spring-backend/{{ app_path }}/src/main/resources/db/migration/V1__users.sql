-- The signed-in user's profile. `subject` is the `sub` claim of the identity provider's token;
-- the profile is created the first time a token's subject calls GET /api/me.
CREATE TABLE users (
    id UUID PRIMARY KEY,
    subject VARCHAR(255) NOT NULL,
    email VARCHAR(320),
    display_name VARCHAR(100) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    CONSTRAINT uq_users_subject UNIQUE (subject)
);
