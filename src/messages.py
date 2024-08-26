import base64
import logs
import config
from meshtastic import mesh_pb2, portnums_pb2, telemetry_pb2
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from collections import deque
import db
import monitor
import math

message_types = portnums_pb2.PortNum.items()
message_ids = deque([], 500)
mqtt_messages = {}


def create_node_id(node_number):
    return f"!{hex(node_number)[2:]}"

def create_node_number(hex_id):
    return int(hex_id.lstrip('!'),16)

def get_nonce(message_packet):
    nonce_packet_id = message_packet.id.to_bytes(8, "little")
    nonce_from_node = getattr(message_packet, "from").to_bytes(8, "little")
    nonce = nonce_packet_id + nonce_from_node
    return nonce

def decode_encrypted(message_packet):
    try:
        key_bytes = base64.b64decode(config.padded_key.encode('ascii'))
        nonce = get_nonce(message_packet)

        cipher = Cipher(algorithms.AES(key_bytes), modes.CTR(nonce), backend=default_backend())
        decryptor = cipher.decryptor()
        decrypted_bytes = decryptor.update(message_packet.encrypted) + decryptor.finalize()

        data = mesh_pb2.Data()
        data.ParseFromString(decrypted_bytes)
        message_packet.decoded.CopyFrom(data)

        if message_packet.decoded.portnum == portnums_pb2.NODEINFO_APP:
            info = mesh_pb2.User()
            infodst = message_packet.to
            info.ParseFromString(message_packet.decoded.payload)
            logs.logging.debug("NODEINFO_APP: %s DST: %s", info, infodst)
        elif message_packet.decoded.portnum == portnums_pb2.POSITION_APP:
            pos = mesh_pb2.Position()
            pos.ParseFromString(message_packet.decoded.payload)
            #logs.logging.debug("POSITION_APP: %s", pos)
        elif message_packet.decoded.portnum == portnums_pb2.TELEMETRY_APP:
            logs.logging.debug("TELEM")
            tel = telemetry_pb2.Telemetry()
            tel.ParseFromString(message_packet.decoded.payload)
            #logs.logging.debug("TELEMETRY_APP: %s", tel)
        elif message_packet.decoded.portnum == portnums_pb2.TEXT_MESSAGE_APP:
            text_payload = message_packet.decoded.payload.decode("utf-8")
            #logs.logging.info("TEXT_MESSAGE_APP: %s", text_payload)
        else:
            loc = next((i for i, v in enumerate(message_types) if v[1] == message_packet.decoded.portnum), None)
            if loc is not None:
                type = message_types[loc][0]
                logs.logging.warning(logs.Fore.RED + "Unknown App %d %s" % (message_packet.decoded.portnum, type) + logs.Style.RESET_ALL)
            else:
                logs.logging.warning("UNKNOWN APP...")

    except Exception as e:
        logs.logging.warning("Decryption failed: %s", str(e))
    finally:
        node_db(message_packet, info if 'info' in locals() else None, pos if 'pos' in locals() else None, tel if 'tel' in locals() else None)

def record_mqtt(message_id,mqtt_node):
    with db.psycopg.connect(db.db_connection_string) as conn:
        with conn.cursor() as cursor:
            node_num = create_node_number(mqtt_node)
            timestamp = logs.timenow()
            cursor.execute("INSERT INTO mqtt (node, msgid, timestamp) VALUES (%s, %s, %s)", (node_num, message_id, timestamp))
        conn.commit()


def message_seen(message_packet,mqtt_node):
    message_id = message_packet.id
    record_mqtt(message_id,mqtt_node)
    if message_id in message_ids:
        return True
    message_ids.append(message_id)
    return False

def create_statement_node(data,sender,timestamp):
    try:
        fields = data.ListFields()
        if fields:
            statement = 'UPDATE nodes SET'
            for field, value in fields:
                rValue = round(value,3)
                statement += f" {field.name}={rValue},"
            statement += f" LastHeard='{timestamp}' WHERE id={sender}"
        else:
            statement = None
            #logs.logging.info(f"Field name: {field.name}, Field value: {rValue}")
    except Exception as e:
        logs.logging.info(e)
        statement = None
    return statement

def create_statement_telem(data,sender,table,timestamp):
    try:
        fields = data.ListFields()
        if fields:
            statement = f'INSERT INTO {table} ('
            statement2 = ""
            for field, value in fields:
                rValue = round(value,3)
                if math.isnan(rValue):
                    rValue= "NULL"
                statement += f'{field.name}, '
                statement2 += f'{rValue}, '
            statement += 'node, timestamp'
            statement2 += f"{sender}, '{timestamp}')"
            statement = statement + ') VALUES (' + statement2
        else:
            statement = None
            #logs.logging.info(f"Field name: {field.name}, Field value: {rValue}")
    except Exception as e:
        logs.logging.error(e)
        statement = None
    return statement


def node_db(message_packet, info, pos, tel):
    sender = str(getattr(message_packet, "from"))
    nid = create_node_id(int(sender))
    with db.psycopg.connect(db.db_connection_string) as conn:
        with conn.cursor() as cursor:
            #lastHeard = message_packet.rx_time
            timestamp = logs.timenow()
            hopcount = message_packet.hop_start
            cursor.execute("SELECT id FROM nodes WHERE id=%s", (sender,))
            if not cursor.fetchall():
                cursor.execute("INSERT INTO nodes (id, hexid) VALUES (%s, %s)", (sender, nid))
                logs.logging.info("New node added to DB")
            infodst = message_packet.to
            cursor.execute("INSERT INTO nodeinfo (node, dest, timestamp) VALUES (%s, %s, %s)",(sender,infodst, timestamp))
            monitor.check_offline_monitored_node(sender)
            cursor.execute('UPDATE nodes SET online=True, hopcount=%s, LastHeard=%s WHERE id=%s', (hopcount, timestamp, sender))
            if info:
                cursor.execute('UPDATE nodes SET long_name=%s, short_name=%s, hardware=%s, role=%s WHERE id=%s',
                               (info.long_name, info.short_name, info.hw_model, info.role, sender))
            elif pos:
                lat = str(pos.latitude_i / 10000000) if pos.latitude_i else None
                lon = str(pos.longitude_i / 10000000) if pos.longitude_i else None
                alt = str(pos.altitude)
                logs.logging.debug('Lat: %s Lon: %s Alt: %s',lat,lon,alt)
                if int(alt) > 32000:
                    logs.logging.warning("Impossible ALT: %s from: %s", alt, nid)
                    alt = None
                cursor.execute('UPDATE nodes SET latitude=%s, longitude=%s, altitude=%s WHERE id=%s', (lat, lon, alt, sender))
            elif tel:

                dev = tel.device_metrics
                env = tel.environment_metrics
                pwr = tel.power_metrics

                statement ={}
                statement['nodes'] = create_statement_node(dev,sender,timestamp)
                statement['telem'] = create_statement_telem(dev,sender,'telemetry',timestamp)
                statement['power'] = create_statement_telem(pwr,sender,'power',timestamp)
                statement['env'] = create_statement_telem(env,sender,'environment',timestamp)

                for sql in statement.values():
                    if sql:
                        try:
                            cursor.execute(sql)
                        except Exception as e:
                            logs.logging.info(sql)
                            logs.logging.error(e)

            conn.commit()