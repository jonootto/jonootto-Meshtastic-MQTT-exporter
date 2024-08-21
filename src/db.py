import psycopg
import config
import logs

db_connection_string = f"dbname={config.db_name} host={config.db_host} user={config.db_user} password={config.db_pass} port={config.db_port}"
nodb_connection_string = f"host={config.db_host} user={config.db_user} password={config.db_pass} port={config.db_port}"

def check_db():
    exists = False
    statement="SELECT datname FROM pg_database;"
    try:
        with psycopg.connect(nodb_connection_string) as conn:
            with conn.cursor() as cursor:
                cursor.execute(statement)
                rows = cursor.fetchall()
                for row in rows:
                    if row[0] == 'meshtastic':
                        exists = True
    except psycopg.Error:
        exists = False
    return exists

def create_db():
        logs.logging.info('Creating meshtastic DB')
        statement="CREATE DATABASE meshtastic;"
        with psycopg.connect(nodb_connection_string) as conn:
            conn.autocommit = True
            with conn.cursor() as cursor:
                cursor.execute(statement)
            conn.commit()


def load_db():
    statement = "SELECT * FROM nodes"
    with psycopg.connect(db_connection_string) as conn:
        with conn.cursor() as cursor:
            cursor.execute(statement)
            rows = cursor.fetchall()
            node_info = {str(row[0]): {desc.name: value for desc, value in zip(cursor.description, row)} for row in rows}
    return node_info

def setup_tables():
    statements = [
        """CREATE TABLE IF NOT EXISTS nodes (
            id BIGINT PRIMARY KEY,
            hexid VARCHAR(9),
            long_name VARCHAR(128),
            short_name VARCHAR(8),
            hardware VARCHAR(32),
            latitude decimal,
            longitude decimal,
            altitude smallint,
            battery_level smallint,
            voltage decimal,
            channel_utilization decimal,
            air_util_tx decimal,
            role VARCHAR(32),
            hopcount smallint,
            LastHeard TIMESTAMPTZ,
            online boolean
        );""",
        """CREATE TABLE IF NOT EXISTS telemetry (
            id SERIAL PRIMARY KEY,
            node BIGINT REFERENCES nodes(id),
            timestamp TIMESTAMPTZ NOT NULL,
            battery_level smallint,
            voltage decimal,
            channel_utilization decimal,
            air_util_tx decimal
        );"""
    ]
    try:
        with psycopg.connect(db_connection_string) as conn:
            for statement in statements:
                with conn.cursor() as cursor:
                    cursor.execute(statement)
                conn.commit()
    except psycopg.Error as e:
        logs.logging.error(e)


def cleanup_old():
    logs.logging.info("Cleaning DB")
    with psycopg.connect(db_connection_string) as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM telemetry WHERE timestamp < now() - interval '30 days'")
        conn.commit()