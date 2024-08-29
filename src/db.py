import psycopg
import config
import logs
import meshtastic
import dbvars

nodb_connection_string = f"host={config.db_host} user={config.db_user} password={config.db_pass} port={config.db_port}"
db_connection_string = f"dbname={config.db_name} {nodb_connection_string}"

reverse_type_map = {v: k for k, v in dbvars.FieldDescriptor.__dict__.items() if k.startswith('TYPE_')}

def get_field_type(number):
    return reverse_type_map.get(number,0)

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

def run_sql(statements):
    try:
        with psycopg.connect(db_connection_string) as conn:
            for statement in statements.values():
                with conn.cursor() as cursor:
                    cursor.execute(statement)
            conn.commit()
    except psycopg.Error as e:
        logs.logging.error(e)


def create_column_statement(columns,tablename):
    statement = {}
    header = f"ALTER TABLE {tablename} ADD COLUMN IF NOT EXISTS "
    for column_name, column_type in columns.items():
        statement[column_name] =  f'{header} {column_name} {column_type};'
    return statement


def setup_tables():
    create_statements = {}
    create_statements["nodes"] = """CREATE TABLE IF NOT EXISTS nodes (id BIGINT PRIMARY KEY);"""
    create_statements["environment"] = """CREATE TABLE IF NOT EXISTS environment (id SERIAL PRIMARY KEY,node BIGINT REFERENCES nodes(id),timestamp TIMESTAMPTZ NOT NULL);"""
    create_statements["telemetry"] =  """CREATE TABLE IF NOT EXISTS telemetry (id SERIAL PRIMARY KEY, node BIGINT REFERENCES nodes(id), timestamp TIMESTAMPTZ NOT NULL);"""
    create_statements["power"] = """CREATE TABLE IF NOT EXISTS power (id SERIAL PRIMARY KEY, node BIGINT REFERENCES nodes(id), timestamp TIMESTAMPTZ NOT NULL);"""
    create_statements["nodeinfo"]  = """CREATE TABLE IF NOT EXISTS nodeinfo (id SERIAL PRIMARY KEY, node BIGINT REFERENCES nodes(id), dest BIGINT, timestamp TIMESTAMPTZ NOT NULL);"""
    create_statements["mqtt"]  = """CREATE TABLE IF NOT EXISTS mqtt (id SERIAL PRIMARY KEY, node BIGINT, msgid BIGINT, sender BIGINT, timestamp TIMESTAMPTZ NOT NULL);"""
    create_statements["neighbours"]  = """CREATE TABLE IF NOT EXISTS neighbours (id SERIAL PRIMARY KEY, node BIGINT, remotenode BIGINT, SNR FLOAT, timestamp TIMESTAMPTZ NOT NULL, UNIQUE (node, remotenode));"""


    run_sql(create_statements)
    node_statements = create_column_statement(dbvars.node_columns,"nodes")
    run_sql(node_statements)
    add_columns("environment",meshtastic.telemetry_pb2.EnvironmentMetrics.DESCRIPTOR)
    add_columns("telemetry",meshtastic.telemetry_pb2.DeviceMetrics.DESCRIPTOR)
    add_columns("power",meshtastic.telemetry_pb2.PowerMetrics.DESCRIPTOR)


def add_columns(name,descriptor):
    fields = get_proto_fields(descriptor)
    statements = create_column_statement(fields,name)
    logs.logging.debug(statements)
    run_sql(statements)

def cleanup_old():
    logs.logging.info("Cleaning DB")
    with psycopg.connect(db_connection_string) as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE';")
            tables = cursor.fetchall()
            tables.remove(('nodes',))
            tables.remove(('mqtt',))
            for table in tables:
                # trunk-ignore(bandit/B608)
                query = f"DELETE FROM {table[0]} WHERE timestamp < now() - interval '30 days'"
                cursor.execute(query)
            query = "DELETE FROM mqtt WHERE timestamp < now() - interval '3 days'"
            cursor.execute(query)
        conn.commit()

def get_postgres_type(protobuf_type_number):
    return dbvars.protobuf_to_postgres_map.get(protobuf_type_number, "TEXT")


def get_proto_fields(descriptor):
    fields = {}
    for field in descriptor.fields:
        field_name = field.name
        field_type = field.type
        pg_type = get_postgres_type(field_type)
        fields[field_name] = pg_type
    return fields
