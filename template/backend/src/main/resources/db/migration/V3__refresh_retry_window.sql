ALTER TABLE users ADD COLUMN previous_refresh_token_version INTEGER;
ALTER TABLE users ADD COLUMN refresh_rotated_at TIMESTAMP WITH TIME ZONE;
