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
            #logs.logging.debug("NODEINFO_APP: %s", info)
        elif message_packet.decoded.portnum == portnums_pb2.POSITION_APP:
            pos = mesh_pb2.Position()
            pos.ParseFromString(message_packet.decoded.payload)
            #logs.logging.debug("POSITION_APP: %s", pos)
        elif message_packet.decoded.portnum == portnums_pb2.TELEMETRY_APP:
            logs.logging.debug("TELEM")
            tel = telemetry_pb2.Telemetry()
            telemetry_pb2.Telemetry()
            tel.ParseFromString(message_packet.decoded.payload)
            logs.logging.debug("TELEMETRY_APP: %s", tel)
        elif message_packet.decoded.portnum == portnums_pb2.TEXT_MESSAGE_APP:
            text_payload = message_packet.decoded.payload.decode("utf-8")
            logs.logging.info("TEXT_MESSAGE_APP: %s", text_payload)
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


def message_seen(message_packet):
    message_id = message_packet.id
    if message_id in message_ids:
        return True
    message_ids.append(message_id)
    return False

def node_db(message_packet, info, pos, tel):
    sender = str(getattr(message_packet, "from"))
    nid = create_node_id(int(sender))
    with db.psycopg.connect(db.db_connection_string) as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM nodes WHERE id=%s", (sender,))
            if not cursor.fetchall():
                cursor.execute("INSERT INTO nodes (id, hexid) VALUES (%s, %s)", (sender, nid))
                logs.logging.info("New node added to DB")

            lastHeard = message_packet.rx_time
            hopcount = message_packet.hop_start
            timestamp = datetime.datetime.fromtimestamp(lastHeard, datetime.UTC)
            monitor.check_offline_monitored_node(sender)
            cursor.execute('UPDATE nodes SET online=True, hopcount=%s, LastHeard=%s WHERE id=%s', (hopcount, timestamp, sender))

            if info:
                cursor.execute('UPDATE nodes SET long_name=%s, short_name=%s, hardware=%s, role=%s WHERE id=%s',
                               (info.long_name, info.short_name, info.hw_model, info.role, sender))
            elif pos:
                lat = str(pos.latitude_i / 10000000) if pos.latitude_i else None
                lon = str(pos.longitude_i / 10000000) if pos.longitude_i else None
                alt = str(pos.altitude)
                logs.logging.info('Lat: %s Lon: %s Alt: %s',lat,lon,alt)
                if int(alt) > 32000:
                    logs.logging.warning("Impossible ALT: %s from: %s", alt, nid)
                    alt = None
                cursor.execute('UPDATE nodes SET latitude=%s, longitude=%s, altitude=%s WHERE id=%s', (lat, lon, alt, sender))
            elif tel:
                dev = tel.device_metrics
                env = tel.environment_metrics
                pwr = tel.power_metrics
                try:
                    #telem = {metric: str(round(getattr(dev, metric, 0), 3)) if getattr(dev, metric, 0) != 0 else None
                    #     for metric in ["battery_level", "voltage", "channel_utilization", "air_util_tx","uptime_seconds"]}
                    for field, value in dev.ListFields():
                        rValue = round(value,2)
                        logs.logging.info(f"Field name: {field.name}, Field value: {rValue}")
                except Exception as e:
                    logs.logging.info(e)
                try:
                    #environment = {metric: str(round(getattr(env, metric, 0), 3)) if getattr(env, metric, 0) != 0 else None
                    #     for metric in ["relative_humidity", "temperature","barometric_pressure"]}
                    for field, value in env.ListFields():
                        rValue = round(value,2)
                        logs.logging.info(f"Field name: {field.name}, Field value: {rValue}")
                except Exception as e:
                    logs.logging.info(e)
                try:
                    #power = {metric: str(round(getattr(pwr, metric, 0), 3)) if getattr(pwr, metric, 0) != 0 else None
                    #     for metric in ["ch1_voltage", "ch1_current","ch2_voltage", "ch2_current","ch3_voltage", "ch3_current"]}
                    for field, value in pwr.ListFields():
                        rValue = round(value,2)
                        logs.logging.info(f"Field name: {field.name}, Field value: {rValue}")
                except Exception as e:
                    logs.logging.info(e)



                if any(telem.values()):
                    #if nid == "!43560564" or nid == "!43563a10":

                    battery_level = telem["battery_level"]
                    voltage = telem["voltage"]
                    channel_utilization = telem["channel_utilization"]
                    air_util_tx = telem["air_util_tx"]
                    uptime_seconds = telem["uptime_seconds"]

                    statement_nodes_base = 'UPDATE nodes SET'
                    statement_nodes_end =  f'WHERE id={sender}'

                    cursor.execute('UPDATE nodes SET battery_level=%s, voltage=%s, channel_utilization=%s, air_util_tx=%s WHERE id=%s',
                                   (telem["battery_level"], telem["voltage"], telem["channel_utilization"], telem["air_util_tx"], sender))
                    cursor.execute('INSERT INTO telemetry (node, timestamp, battery_level, voltage, channel_utilization, air_util_tx) VALUES (%s, %s, %s, %s, %s, %s)',
                                   (sender, timestamp, telem["battery_level"], telem["voltage"], telem["channel_utilization"], telem["air_util_tx"]))
            
                if any(environment.values()):
                    pass
                if any(power.values()):
                    pass
            
            
            conn.commit()