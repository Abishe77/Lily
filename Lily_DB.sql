CREATE TYPE topic_status AS ENUM (
    'urgent',
    'monitor',
    'resolved'
);

CREATE TYPE personality_mode AS ENUM (
    'funny_sarcastic',
    'friendly_encouraging',
    'strict_disciplined',
    'professional',
    'calm_gentle'
);

CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL,
    email VARCHAR(60) UNIQUE NOT NULL,
    hashed_pass VARCHAR(255),
    email_verified BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE auth_accounts (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider VARCHAR(20) NOT NULL,
    provider_user_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(provider, provider_user_id)
);

CREATE TABLE otp_codes (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    email VARCHAR(60) NOT NULL,
    purpose VARCHAR(20) NOT NULL,
    otp VARCHAR(6) NOT NULL,
    attempts INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    UNIQUE(email, purpose)
);

CREATE TABLE login_attempts (
    email VARCHAR(60) PRIMARY KEY,
    attempts INT NOT NULL DEFAULT 0,
    locked_until TIMESTAMPTZ
);

CREATE TABLE oauth_states (
    state VARCHAR(255) PRIMARY KEY,
    code_verifier TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE companions (
    id SERIAL PRIMARY KEY,
    user_id INT UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(20) NOT NULL,
    gender VARCHAR(20) NOT NULL,
    personality_mode personality_mode NOT NULL DEFAULT 'funny_sarcastic',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE style_profiles (
    id SERIAL PRIMARY KEY,
    user_id INT UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    sample_notes_txt TEXT,
    text_style TEXT,
    analysed_style TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE sources (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    extracted_text TEXT NOT NULL,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE notes (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_id INT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    style_profile_id INT REFERENCES style_profiles(id) ON DELETE SET NULL,
    generated_content JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE note_blocks (
    id SERIAL PRIMARY KEY,
    note_id INT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    block_type VARCHAR(30) NOT NULL,
    content JSONB NOT NULL,
    source_reference TEXT,
    metadata JSONB,
    order_index INT NOT NULL
);

CREATE TABLE quizzes (
    id SERIAL PRIMARY KEY,
    note_id INT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    questions_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE quiz_attempts (
    id SERIAL PRIMARY KEY,
    quiz_id INT NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    score INT NOT NULL,
    time_taken_seconds DECIMAL,
    attempted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE weak_topics (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    note_block_id INT REFERENCES note_blocks(id) ON DELETE CASCADE,
    latest_score INT,
    status topic_status NOT NULL,
    next_review TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE refresh_sessions (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at TIMESTAMPTZ,
    last_used_at TIMESTAMPTZ
);

CREATE INDEX idx_auth_accounts_user_id
    ON auth_accounts(user_id);

CREATE INDEX idx_otp_codes_user_id
    ON otp_codes(user_id);

CREATE INDEX idx_sources_user_id
    ON sources(user_id);

CREATE INDEX idx_notes_user_id
    ON notes(user_id);

CREATE INDEX idx_notes_source_id
    ON notes(source_id);

CREATE INDEX idx_note_blocks_note_id
    ON note_blocks(note_id);

CREATE INDEX idx_note_blocks_type
    ON note_blocks(block_type);

CREATE INDEX idx_quizzes_note_id
    ON quizzes(note_id);

CREATE INDEX idx_quiz_attempts_quiz_id
    ON quiz_attempts(quiz_id);

CREATE INDEX idx_quiz_attempts_user_id
    ON quiz_attempts(user_id);

CREATE INDEX idx_weak_topics_user_id
    ON weak_topics(user_id);

CREATE INDEX idx_weak_topics_note_block_id
    ON weak_topics(note_block_id);

CREATE INDEX idx_refresh_sessions_user_id
    ON refresh_sessions(user_id);

CREATE INDEX idx_refresh_sessions_expires_at
    ON refresh_sessions(expires_at);

CREATE TABLE teaching_profiles (
    id SERIAL PRIMARY KEY,

    user_id INT UNIQUE NOT NULL
        REFERENCES users(id) ON DELETE CASCADE,

    preferences JSONB NOT NULL DEFAULT '{}'::jsonb,

    evidence JSONB NOT NULL DEFAULT '[]'::jsonb,

    confidence JSONB NOT NULL DEFAULT '{}'::jsonb,

    user_override JSONB NOT NULL DEFAULT '{}'::jsonb,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_teaching_profiles_user_id
    ON teaching_profiles(user_id);



