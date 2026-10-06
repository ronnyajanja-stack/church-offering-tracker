-- ====================================================================
-- CHURCH OFFERING & TITHE TRACKER DATABASE SCHEMA
-- Compatible with SQLite, Flask, and Google OAuth 2.0
-- ====================================================================

-- 1. Users Table (Supports local email/phone signup and Google SSO)
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    phone TEXT UNIQUE,                     -- Nullable initially for Google SSO sign-ins
    password_hash TEXT,                    -- Nullable for Google SSO sign-ins
    google_id TEXT UNIQUE,                 -- Google Subject Identifier (sub ID)
    role TEXT CHECK(role IN ('admin', 'treasurer', 'member')) DEFAULT 'member',
    reset_token TEXT,                      -- Password recovery token
    reset_token_expiry TIMESTAMP,          -- Token expiration timestamp
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Fund Categories (Tithes, General Offering, Project Funds, etc.)
CREATE TABLE IF NOT EXISTS fund_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT
);

-- 3. Financial Transactions Table (Inflows & Outflows)
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    category_id INTEGER NOT NULL,
    transaction_type TEXT CHECK(transaction_type IN ('contribution', 'disbursement')) NOT NULL,
    amount REAL NOT NULL,
    payment_method TEXT CHECK(payment_method IN ('Cash', 'M-Pesa', 'Bank Transfer', 'Cheque')) NOT NULL,
    reference_no TEXT,                     -- M-Pesa transaction code, bank reference, or envelope #
    service_date DATE NOT NULL,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL,
    FOREIGN KEY (category_id) REFERENCES fund_categories (id) ON DELETE CASCADE
);

-- 4. Initial Seed Data for Core Church Funds
INSERT OR IGNORE INTO fund_categories (id, name, description) VALUES
(1, 'Tithes', 'Regular individual tithes (10%)'),
(2, 'Sunday General Offering', 'Main sanctuary and mid-week service collections'),
(3, 'Building & Development Fund', 'Church infrastructure, sanctuary expansion, and capital projects'),
(4, 'Missions & Outreach', 'Evangelism, benevolence, and community outreach'),
(5, 'Youth & Children Ministry', 'Sunday school and youth activities');