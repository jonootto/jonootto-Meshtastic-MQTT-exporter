from google.protobuf.descriptor import FieldDescriptor


protobuf_to_postgres_map = {
   FieldDescriptor.TYPE_DOUBLE: "DOUBLE PRECISION",
   FieldDescriptor.TYPE_FLOAT: "REAL",
   FieldDescriptor.TYPE_INT64: "BIGINT",
   FieldDescriptor.TYPE_UINT64: "BIGINT",  # PostgreSQL doesn't have unsigned types, so use BIGINT
   FieldDescriptor.TYPE_INT32: "INTEGER",
   FieldDescriptor.TYPE_FIXED64: "BIGINT",
   FieldDescriptor.TYPE_FIXED32: "INTEGER",
   FieldDescriptor.TYPE_BOOL: "BOOLEAN",
   FieldDescriptor.TYPE_STRING: "TEXT",
   FieldDescriptor.TYPE_GROUP: "TEXT",  # Protobuf groups are deprecated, map to TEXT for storage
   FieldDescriptor.TYPE_MESSAGE: "JSONB",  # Nested messages can be stored as JSONB
   FieldDescriptor.TYPE_BYTES: "BYTEA",
   FieldDescriptor.TYPE_UINT32: "INTEGER",  # PostgreSQL doesn't have unsigned types, so use BIGINT
   FieldDescriptor.TYPE_ENUM: "INTEGER",  # Protobuf enums can be stored as integers
   FieldDescriptor.TYPE_SFIXED32: "INTEGER",
   FieldDescriptor.TYPE_SFIXED64: "BIGINT",
   FieldDescriptor.TYPE_SINT32: "INTEGER",
   FieldDescriptor.TYPE_SINT64: "BIGINT",
}

node_columns = {
    "hexid": "VARCHAR(9)",
    "long_name": "VARCHAR(64)",
    "short_name": "VARCHAR(8)",
    "hardware": "VARCHAR(32)",
    "latitude": "REAL",
    "longitude": "REAL",
    "altitude": "smallint",
    "battery_level": "smallint",
    "voltage": "REAL",
    "uptime_seconds": "int",
    "channel_utilization": "REAL",
    "air_util_tx": "REAL",
    "role": "VARCHAR(32)",
    "hopcount": "smallint",
    "LastHeard": "TIMESTAMPTZ",
    "online": "boolean"
}

