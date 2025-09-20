-- Initialize database with test tables

-- Create source table (tableA)
CREATE TABLE IF NOT EXISTS public.tablea (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(255) UNIQUE,
    age INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create destination table (tableB)
CREATE TABLE IF NOT EXISTS public.tableb (
    id INTEGER PRIMARY KEY,
    name VARCHAR(200),
    email VARCHAR(255),
    age INTEGER,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source_table VARCHAR(50) DEFAULT 'tablea'
);

-- Insert sample data into tableA
INSERT INTO public.tablea (name, email, age) VALUES
    ('田中太郎', 'tanaka@example.com', 25),
    ('佐藤花子', 'sato@example.com', 30),
    ('山田次郎', 'yamada@example.com', 35)
ON CONFLICT (email) DO NOTHING;

-- Create a trigger to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_tablea_updated_at
    BEFORE UPDATE ON public.tablea
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Grant necessary permissions for replication
ALTER TABLE public.tablea REPLICA IDENTITY FULL;
ALTER TABLE public.tableb REPLICA IDENTITY FULL;