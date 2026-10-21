-- =============================================================================
-- CHURCH TREASURY PORTAL - DATABASE SCHEMA
-- SQLite Compatible
-- Supports Inflow (Basket/Fund Collections) and Outflow (Church Expenses)
-- =============================================================================

PRAGMA foreign_keys = ON;

-- -----------------------------------------------------------------------------
-- 1. CHURCH ORGANIZATIONS TABLE
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS churches;

CREATE TABLE churches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT,
    email TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------------------------
-- 2. USERS & ROLES TABLE
-- Roles: CLERK, TREASURER, PASTOR, ADMIN
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS users;

CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    church_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    phone TEXT,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'CLERK',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (church_id) REFERENCES churches(id) ON DELETE CASCADE
);

-- -----------------------------------------------------------------------------
-- 3. CHURCH SUBSCRIPTIONS & GRACE PERIOD TABLE
-- Plans: TRIAL, STANDARD, PREMIUM
-- Cycles: MONTHLY, ANNUAL
-- Status: ACTIVE, EXPIRED, CANCELLED
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS church_subscriptions;

CREATE TABLE church_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    church_id INTEGER NOT NULL,
    plan_tier TEXT NOT NULL DEFAULT 'TRIAL',
    billing_cycle TEXT NOT NULL DEFAULT 'MONTHLY',
    is_trial INTEGER NOT NULL DEFAULT 1,
    trial_ends_at DATE,
    expires_at DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (church_id) REFERENCES churches(id) ON DELETE CASCADE
);

-- -----------------------------------------------------------------------------
-- 4. AGGREGATE GIVING RECORDS (INFLOW / OFFERING COLLECTIONS)
-- No individual member tracking; captures counted offering categories
-- Categories: NORMAL_OFFERING, TITHE, THANKSGIVING, DEVELOPMENT,
--             SUNDAY_SCHOOL, MISSIONS, WELFARE, FIRST_FRUITS, OTHER
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS giving_records;

CREATE TABLE giving_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    church_id INTEGER NOT NULL,
    recorded_by_user_id INTEGER NOT NULL,
    service_date DATE NOT NULL,
    service_type TEXT NOT NULL DEFAULT 'FIRST_SERVICE', -- FIRST_SERVICE, SECOND_SERVICE, MIDWEEK, SPECIAL
    category TEXT NOT NULL,                             -- TITHE, NORMAL_OFFERING, THANKSGIVING, etc.
    payment_method TEXT NOT NULL DEFAULT 'CASH',        -- CASH, MPESA, BANK_TRANSFER, CHEQUE
    reference_code TEXT,                                -- M-Pesa receipt, cheque number, or envelope ref
    amount DECIMAL(12, 2) NOT NULL,
    notes TEXT,                                         -- Batch / counting details
    batch_status TEXT NOT NULL DEFAULT 'PENDING',       -- PENDING, LOCKED
    reconciled_by_user_id INTEGER,
    reconciled_at DATETIME,
    bank_slip_ref TEXT,                                 -- Deposit slip reference when banked
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (church_id) REFERENCES churches(id) ON DELETE CASCADE,
    FOREIGN KEY (recorded_by_user_id) REFERENCES users(id) ON DELETE RESTRICT,
    FOREIGN KEY (reconciled_by_user_id) REFERENCES users(id) ON DELETE RESTRICT
);

-- -----------------------------------------------------------------------------
-- 5. EXPENSES & DISBURSAL RECORDS (OUTFLOW / EXPENDITURES)
-- Tracks operational payments, pastoral honoraria, utilities, benevolence, etc.
-- Categories: HONORARIUM, UTILITIES, RENT_FACILITY, EQUIPMENT_MAINTENANCE,
--             WELFARE_DISBURSAL, SUNDAY_SCHOOL_EXPENSE, MISSIONS_OUTREACH,
--             ADMIN_OPERATIONAL, TRANSPORT, OTHER_EXPENSE
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS expenses;

CREATE TABLE expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    church_id INTEGER NOT NULL,
    recorded_by_user_id INTEGER NOT NULL,
    expense_date DATE NOT NULL,
    category TEXT NOT NULL,
    amount DECIMAL(12, 2) NOT NULL,
    payment_method TEXT NOT NULL DEFAULT 'CASH',        -- CASH, MPESA, BANK_TRANSFER, CHEQUE
    payee TEXT NOT NULL,                                -- Person, vendor, utility, or minister paid
    voucher_ref TEXT,                                   -- Payment voucher or receipt number
    approved_by TEXT,                                   -- Sign-off by Pastor or Treasurer
    notes TEXT,                                         -- Purpose and description of expenditure
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (church_id) REFERENCES churches(id) ON DELETE CASCADE,
    FOREIGN KEY (recorded_by_user_id) REFERENCES users(id) ON DELETE RESTRICT
);

-- -----------------------------------------------------------------------------
-- PERFORMANCE & AUDIT INDEXES
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_giving_church_date 
    ON giving_records (church_id, service_date);

CREATE INDEX IF NOT EXISTS idx_giving_category 
    ON giving_records (church_id, category);

CREATE INDEX IF NOT EXISTS idx_expenses_church_date 
    ON expenses (church_id, expense_date);

CREATE INDEX IF NOT EXISTS idx_expenses_category 
    ON expenses (church_id, category);

CREATE INDEX IF NOT EXISTS idx_subs_church_status 
    ON church_subscriptions (church_id, status);

CREATE INDEX IF NOT EXISTS idx_users_email_phone 
    ON users (email, phone);