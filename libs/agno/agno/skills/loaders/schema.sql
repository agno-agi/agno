-- Database schema for skills stored in PostgreSQL
-- Run this to set up the tables for DatabaseSkills loader

-- Skills table
CREATE TABLE IF NOT EXISTS skills (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    description TEXT,
    instructions TEXT NOT NULL,
    metadata JSONB,
    license VARCHAR(100),
    compatibility VARCHAR(100),
    allowed_tools TEXT[],
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Scripts table (references script files)
CREATE TABLE IF NOT EXISTS scripts (
    id SERIAL PRIMARY KEY,
    skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    content TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(skill_id, file_name)
);

-- References table (references documentation files)
CREATE TABLE IF NOT EXISTS references (
    id SERIAL PRIMARY KEY,
    skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    content TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(skill_id, file_name)
);

-- Indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_skills_name ON skills(name);
CREATE INDEX IF NOT EXISTS idx_scripts_skill_id ON scripts(skill_id);
CREATE INDEX IF NOT EXISTS idx_references_skill_id ON references(skill_id);

-- Example: Insert a sample skill with scripts and references
/*
INSERT INTO skills (name, description, instructions, metadata)
VALUES (
    'sample_skill',
    'A sample skill for testing',
    '---\nname: sample_skill\ndescription: A sample skill\n---\n\nThis is the instructions body.',
    '{"version": "1.0", "author": "test"}'
);

INSERT INTO scripts (skill_id, name, file_name, content)
VALUES (
    (SELECT id FROM skills WHERE name = 'sample_skill'),
    'Example Script',
    'example.sh',
    '#!/bin/bash\necho "Hello from script"'
);

INSERT INTO references (skill_id, name, file_name, content)
VALUES (
    (SELECT id FROM skills WHERE name = 'sample_skill'),
    'Example Reference',
    'README.txt',
    'This is reference documentation.'
);
*/
