-- Transactions table
CREATE TABLE transactions (
    id UUID NOT NULL,
    reference VARCHAR(40) NOT NULL UNIQUE,
    amount DECIMAL(19, 2) NOT NULL,
    currency VARCHAR(3) NOT NULL,
    description VARCHAR(2000),
    type VARCHAR(20) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    created_by UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_transactions PRIMARY KEY (id),
    CONSTRAINT fk_transactions_users
        FOREIGN KEY (created_by) REFERENCES users(id),
    CONSTRAINT chk_transactions_type
        CHECK (type = ANY (ARRAY['CHARGE', 'REFUND', 'PAYOUT'])),
    CONSTRAINT chk_transactions_status
        CHECK (status = ANY (ARRAY['PENDING', 'SETTLED', 'FAILED', 'CANCELLED'])),
    CONSTRAINT chk_transactions_currency
        CHECK (char_length(currency) = 3)
);

CREATE INDEX idx_transactions_status ON transactions(status);
CREATE INDEX idx_transactions_created_by ON transactions(created_by);
CREATE INDEX idx_transactions_created_at ON transactions(created_at DESC);
CREATE INDEX idx_transactions_reference ON transactions(reference);
