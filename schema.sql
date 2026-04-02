CREATE TABLE IF NOT EXISTS matches (
    id TEXT PRIMARY KEY,
    created_at TEXT,
    finished_at TEXT,
    variant TEXT,
    base_score INTEGER,
    duration TEXT
);

CREATE TABLE IF NOT EXISTS match_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id TEXT,
    player_name TEXT,
    average REAL,
    first9_average REAL,
    darts_thrown INTEGER,
    checkouts_hit INTEGER,
    checkout_percent REAL,
    plus60 INTEGER,
    plus100 INTEGER,
    plus140 INTEGER,
    total180 INTEGER,
    FOREIGN KEY(match_id) REFERENCES matches(id)
);

CREATE TABLE IF NOT EXISTS legs (
    id TEXT PRIMARY KEY,
    match_id TEXT,
    set_number INTEGER,
    leg_number INTEGER,
    winner_name TEXT,
    created_at TEXT,
    finished_at TEXT,
    FOREIGN KEY(match_id) REFERENCES matches(id)
);

CREATE TABLE IF NOT EXISTS leg_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    leg_id TEXT,
    player_name TEXT,
    average REAL,
    first9_average REAL,
    darts_thrown INTEGER,
    score INTEGER,
    checkout_points INTEGER,
    plus60 INTEGER,
    plus100 INTEGER,
    plus140 INTEGER,
    total180 INTEGER,
    FOREIGN KEY(leg_id) REFERENCES legs(id)
);

CREATE TABLE IF NOT EXISTS turns (
    id TEXT PRIMARY KEY,
    leg_id TEXT,
    player_name TEXT,
    round_number INTEGER,
    score INTEGER,
    points_left INTEGER,
    busted BOOLEAN,
    FOREIGN KEY(leg_id) REFERENCES legs(id)
);

CREATE TABLE IF NOT EXISTS throws (
    id TEXT PRIMARY KEY,
    turn_id TEXT,
    dart_number INTEGER,
    segment_name TEXT,
    segment_number INTEGER,
    segment_bed TEXT,
    multiplier INTEGER,
    coords_x REAL,
    coords_y REAL,
    FOREIGN KEY(turn_id) REFERENCES turns(id)
);