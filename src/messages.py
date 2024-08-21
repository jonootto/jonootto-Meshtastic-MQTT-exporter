import base64
import logs
import config
import json
from meshtastic import mesh_pb2, portnums_pb2, telemetry_pb2
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from collections import deque
import db
import datetime
import monitor


message_types = portnums_pb2.PortNum.items()
message_ids = deque([], 200)


def create_node_id(node_number):
    return f"!{hex(node_number)[2:]}"


def get_nonce(message_packet):
    nonce_packet_id = getattr(message_packet, "id").to_bytes(8, "little")
    nonce_from_node = getattr(message_packet, "from").to_bytes(8, "little")
    nonce = nonce_packet_id + nonce_from_node
    return nonce

def decode_encrypted(message_packet):
    try:
        key_bytes = base64.b64decode(config.padded_key.encode('ascii'))
        nonce = get_nonce(message_packet)

        cipher = Cipher(algorithms.AES(key_bytes), modes.CTR(nonce), backend=default_backend())
        decryptor = cipher.decryptor()
        decrypted_bytes = decryptor.update(getattr(message_packet, "encrypted")) + decryptor.finalize()

        data = mesh_pb2.Data()
        data.ParseFromString(decrypted_bytes)
        message_packet.decoded.CopyFrom(data)

        if message_packet.decoded.portnum == portnums_pb2.NODEINFO_APP:
            info = mesh_pb2.User()
            info.ParseFromString(message_packet.decoded.payload)
            logs.logging.debug("NODEINFO_APP: %s", info)
        elif message_packet.decoded.portnum == portnums_pb2.POSITION_APP:
            pos = mesh_pb2.Position()
            pos.ParseFromString(message_packet.decoded.payload)
            logs.logging.debug("POSITION_APP: %s", pos)
        elif message_packet.decoded.portnum == portnums_pb2.TELEMETRY_APP:
            env = telemetry_pb2.Telemetry()
            env.ParseFromString(message_packet.decoded.payload)
            logs.logging.debug("TELEMETRY_APP: %s", env)
        elif message_packet.decoded.portnum == portnums_pb2.TEXT_MESSAGE_APP:
            text_payload = message_packet.decoded.payload.decode("utf-8")
            logs.logging.info("TEXT_MESSAGE_APP: %s", text_payload)
        else:
            loc = next((i for i, v in enumerate(message_types) if v[1] == message_packet.decoded.portnum), None)
            if loc is not None:
                type = message_types[loc][0]
                logs.logging.warning(logs.Fore.RED + "Unknown App %d %s" % (message_packet.decoded.portnum, type) + logs.Style.RESET_ALL)

    except Exception as e:
        logs.logging.warning("Decryption failed: %s", str(e))
    finally:
        node_db(message_packet, info if 'info' in locals() else None, pos if 'pos' in locals() else None, env if 'env' in locals() else None)


def message_seen(message_packet):
    message_id = getattr(message_packet, "id")
    if message_id in message_ids:
        return True
    message_ids.append(message_id)
    return False

def node_db(message_packet, info, pos, env):
    sender = str(getattr(message_packet, "from"))
    with db.psycopg.connect(db.db_connection_string) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM nodes WHERE id=%s", (sender,))
        if not cursor.fetchall():
            nid = create_node_id(int(sender))
            cursor.execute("INSERT INTO nodes (id, hexid) VALUES (%s, %s)", (sender, nid))
            logs.logging.info("New node added to DB")

        lastHeard = getattr(message_packet, "rx_time")
        hopcount = getattr(message_packet, "hop_start")
        timestamp = datetime.datetime.fromtimestamp(lastHeard, datetime.UTC)
        monitor.check_offline_monitored_node(sender)
        cursor.execute('UPDATE nodes SET online=True, hopcount=%s, LastHeard=%s WHERE id=%s', (hopcount, timestamp, sender))

        if info:
            cursor.execute('UPDATE nodes SET long_name=%s, short_name=%s, hardware=%s, role=%s WHERE id=%s',
                           (info.long_name, info.short_name, info.hw_model, info.role, sender))
        elif pos:
            lat = str(getattr(pos, "latitude_i") / 10000000) if pos.latitude_i else None
            lon = str(getattr(pos, "longitude_i") / 10000000) if pos.longitude_i else None
            alt = str(getattr(pos, "altitude", None))
            if int(alt) > 32000:
                logs.logging.warning("Impossible ALT: %s from: %s", alt, create_node_id(int(sender)))
                alt = None
            cursor.execute('UPDATE nodes SET latitude=%s, longitude=%s, altitude=%s WHERE id=%s', (lat, lon, alt, sender))
        elif env:
            dev = getattr(env, "device_metrics")
            telem = {metric: str(round(getattr(dev, metric, 0), 3)) if getattr(dev, metric, 0) != 0 else None
                     for metric in ["battery_level", "voltage", "channel_utilization", "air_util_tx"]}
            telem["id"] = sender
            if any(telem.values()):
                logs.logging.debug(json.dumps(telem, indent=4))
                cursor.execute('UPDATE nodes SET battery_level=%s, voltage=%s, channel_utilization=%s, air_util_tx=%s WHERE id=%s',
                               (telem["battery_level"], telem["voltage"], telem["channel_utilization"], telem["air_util_tx"], telem["id"]))
                cursor.execute('INSERT INTO telemetry (node, timestamp, battery_level, voltage, channel_utilization, air_util_tx) VALUES (%s, %s, %s, %s, %s, %s)',
                               (telem["id"], timestamp, telem["battery_level"], telem["voltage"], telem["channel_utilization"], telem["air_util_tx"]))
        conn.commit()