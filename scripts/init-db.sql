-- Financial Solvency Truth Engine - Database Initialization
-- This script creates the initial schema for the Truth Engine

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Create tables
-- Note: SQLAlchemy models will create the actual tables
-- This file ensures the database is ready

-- Grant permissions
GRANT ALL PRIVILEGES ON DATABASE truth_engine TO truth_engine;

-- Create schema if using namespaces
-- CREATE SCHEMA IF NOT EXISTS truth_engine;

-- Placeholder for future migrations
-- Alembic will manage actual schema migrations in A1+

SELECT 'Database initialized for Truth Engine A0' as status;
