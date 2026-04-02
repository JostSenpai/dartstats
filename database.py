import sqlite3

DB_FILE = "dartstats.db"

def get_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    return conn, conn.cursor()

def init_db():
    print("[DB] Initializing advanced database schema...")
    conn, cursor = get_db()
    with open("schema.sql") as f:
        cursor.executescript(f.read())
    conn.commit()
    conn.close()
    print("[DB] Schema loaded successfully.")

def save_pristine_match(match_data):
    conn, cursor = get_db()
    match_id = match_data.get('id')

    # Prevent duplicate saves
    cursor.execute("SELECT id FROM matches WHERE id=?", (match_id,))
    if cursor.fetchone():
        print(f"[DB-WARNING] Match {match_id} already exists in database. Skipping.")
        conn.close()
        return

    # Map player IDs to Names
    players = {p.get('id', p.get('userId')): p.get('name', 'Unknown') for p in match_data.get('players', [])}

    print(f"[DB] Vaulting Match {match_id} into the database...")

    # 1. Matches Table
    settings = match_data.get('settings', {})
    cursor.execute("""
        INSERT INTO matches (id, created_at, finished_at, variant, base_score, duration)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        match_id, match_data.get('createdAt'), match_data.get('finishedAt'),
        match_data.get('variant'), settings.get('baseScore'), match_data.get('duration')
    ))

    # 2. Match Stats Table
    for stat in match_data.get('matchStats', []):
        p_name = players.get(stat.get('playerId'), 'Unknown')
        cursor.execute("""
            INSERT INTO match_stats (match_id, player_name, average, first9_average, darts_thrown, checkouts_hit, checkout_percent, plus60, plus100, plus140, total180)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            match_id, p_name, stat.get('average'), stat.get('first9Average'),
            stat.get('dartsThrown'), stat.get('checkoutsHit'), stat.get('checkoutPercent'),
            stat.get('plus60'), stat.get('plus100'), stat.get('plus140'), stat.get('total180')
        ))

    # 3. Legs, Turns, and Throws
    for game in match_data.get('games', []):
        leg_id = game.get('id')
        winner_id = game.get('winnerPlayerId')
        winner_name = players.get(winner_id, 'None') if winner_id else 'None'

        cursor.execute("""
            INSERT INTO legs (id, match_id, set_number, leg_number, winner_name, created_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            leg_id, match_id, game.get('set'), game.get('leg'),
            winner_name, game.get('createdAt'), game.get('finishedAt')
        ))

        for turn in game.get('turns', []):
            turn_id = turn.get('id')
            t_player = players.get(turn.get('playerId'), 'Unknown')

            cursor.execute("""
                INSERT INTO turns (id, leg_id, player_name, round_number, score, points_left, busted)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                turn_id, leg_id, t_player, turn.get('round'),
                turn.get('score'), turn.get('points'), turn.get('busted')
            ))

            darts = turn.get('throws', []) or turn.get('darts', [])
            for idx, dart in enumerate(darts):
                dart_id = dart.get('id', f"{turn_id}_{idx}")
                seg = dart.get('segment', {})
                coords = dart.get('coords', {})

                cursor.execute("""
                    INSERT INTO throws (id, turn_id, dart_number, segment_name, segment_number, segment_bed, multiplier, coords_x, coords_y)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    dart_id, turn_id, dart.get('throw', idx),
                    seg.get('name'), seg.get('number'), seg.get('bed'),
                    seg.get('multiplier', dart.get('multiplier', 1)),
                    coords.get('x'), coords.get('y')
                ))

    # 4. Leg Stats Table
    for leg_stat_obj in match_data.get('legStats', []):
        for stat in leg_stat_obj.get('stats', []):
            l_id = stat.get('gameId')
            p_name = players.get(stat.get('playerId'), 'Unknown')

            cursor.execute("""
                INSERT INTO leg_stats (leg_id, player_name, average, first9_average, darts_thrown, score, checkout_points, plus60, plus100, plus140, total180)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                l_id, p_name, stat.get('average'), stat.get('first9Average'),
                stat.get('dartsThrown'), stat.get('score'), stat.get('checkoutPoints'),
                stat.get('plus60'), stat.get('plus100'), stat.get('plus140'), stat.get('total180')
            ))

    conn.commit()
    conn.close()
    print(f"[DB] --- ALL ADVANCED STATS SUCCESSFULLY VAULTED ---")