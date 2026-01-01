-- Treasury Auctions Table
-- Run this in Supabase SQL Editor

CREATE TABLE IF NOT EXISTS treasury_auctions (
    id SERIAL PRIMARY KEY,
    cusip VARCHAR(9) NOT NULL,
    security_type VARCHAR(20) NOT NULL,
    security_term VARCHAR(20),
    auction_date DATE NOT NULL,
    issue_date DATE,
    maturity_date DATE,
    high_yield NUMERIC(10, 6),
    high_discount_rate NUMERIC(10, 6),
    bid_to_cover_ratio NUMERIC(10, 4),
    total_accepted NUMERIC(20, 2),
    total_tendered NUMERIC(20, 2),
    offering_amount NUMERIC(20, 2),
    competitive_accepted NUMERIC(20, 2),
    noncompetitive_accepted NUMERIC(20, 2),
    primary_dealer_accepted NUMERIC(20, 2),
    direct_bidder_accepted NUMERIC(20, 2),
    indirect_bidder_accepted NUMERIC(20, 2),
    reopening BOOLEAN DEFAULT FALSE,
    original_cusip VARCHAR(9),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_treasury_auctions_cusip ON treasury_auctions(cusip);
CREATE INDEX IF NOT EXISTS idx_treasury_auctions_date ON treasury_auctions(auction_date);
CREATE INDEX IF NOT EXISTS idx_treasury_auctions_type ON treasury_auctions(security_type);
CREATE UNIQUE INDEX IF NOT EXISTS idx_treasury_auctions_cusip_date ON treasury_auctions(cusip, auction_date);

-- Enable RLS
ALTER TABLE treasury_auctions ENABLE ROW LEVEL SECURITY;
