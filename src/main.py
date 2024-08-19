import paho.mqtt.client as mqtt
from meshtastic import mesh_pb2, mqtt_pb2, portnums_pb2, telemetry_pb2
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import base64
from collections import deque
from colorama import Fore, Style
import json
import datetime
from zoneinfo import ZoneInfo
import psycopg
from dotenv import load_dotenv
import logging
import os
import random
import smtplib
from email.mime.text import MIMEText
import schedule

load_dotenv()

FORMAT = '%(levelname)s: %(asctime)s - %(message)s'
logging.basicConfig(level=logging.INFO, format=FORMAT, datefmt='%H:%M:%S')

# Environment Variables
db_name = os.environ["DBNAME"]
db_host = os.environ["DBHOST"]
db_user = os.environ["DBUSER"]
db_pass = os.environ["DBPASS"]
db_port = os.environ["DBPORT"]
email_password = os.environ["EPASSWORD"]
email_sender = os.environ["ESENDER"]

# MQTT Configurations
MQTT_BROKER = "mqtt.meshtastic.org"
MQTT_PORT = 1883
MQTT_USERNAME = "meshdev"
MQTT_PASSWORD = "large4cats"
root_topic = "msh/WLG_915/2/e/#"


# Encryption Key
key = "1PG7OiApB1nwvP+rz05pAQ==".replace('-', '+').replace('_', '/')
padded_key = key.ljust(len(key) + ((4 - (len(key) % 4)) % 4), '=')

# Global Variables
message_ids = deque([], 200)
message_types = portnums_pb2.PortNum.items()
watch = {}

def process_message(mp, text_payload, is_encrypted):
    text = {
        "message": text_payload,
        "from": getattr(mp, "from"),
        "id": getattr(mp, "id"),
        "to": getattr(mp, "to")
    }

def decode_encrypted(message_packet):
    try:
        key_bytes = base64.b64decode(padded_key.encode('ascii'))
        nonce_packet_id = getattr(message_packet, "id").to_bytes(8, "little")
        nonce_from_node = getattr(message_packet, "from").to_bytes(8, "little")
        nonce = nonce_packet_id + nonce_from_node

        cipher = Cipher(algorithms.AES(key_bytes), modes.CTR(nonce), backend=default_backend())
        decryptor = cipher.decryptor()
        decrypted_bytes = decryptor.update(getattr(message_packet, "encrypted")) + decryptor.finalize()

        data = mesh_pb2.Data()
        data.ParseFromString(decrypted_bytes)
        message_packet.decoded.CopyFrom(data)

        if message_packet.decoded.portnum == portnums_pb2.NODEINFO_APP:
            info = mesh_pb2.User()
            info.ParseFromString(message_packet.decoded.payload)
            logging.debug("NODEINFO_APP: %s", info)
        elif message_packet.decoded.portnum == portnums_pb2.POSITION_APP:
            pos = mesh_pb2.Position()
            pos.ParseFromString(message_packet.decoded.payload)
            logging.debug("POSITION_APP: %s", pos)
        elif message_packet.decoded.portnum == portnums_pb2.TELEMETRY_APP:
            env = telemetry_pb2.Telemetry()
            env.ParseFromString(message_packet.decoded.payload)
            logging.debug("TELEMETRY_APP: %s", env)
        elif message_packet.decoded.portnum == portnums_pb2.TEXT_MESSAGE_APP:
            text_payload = message_packet.decoded.payload.decode("utf-8")
            process_message(message_packet, text_payload, is_encrypted=True)
            logging.info("TEXT_MESSAGE_APP: %s", text_payload)
        else:
            loc = next((i for i, v in enumerate(message_types) if v[1] == message_packet.decoded.portnum), None)
            if loc is not None:
                type = message_types[loc][0]
                logging.warning(Fore.RED + "Unknown App %d %s" % (message_packet.decoded.portnum, type) + Style.RESET_ALL)
    except Exception as e:
        logging.warning("Decryption failed: %s", str(e))
    finally:
        node_db(message_packet, info if 'info' in locals() else None, pos if 'pos' in locals() else None, env if 'env' in locals() else None)

def on_connect(client, userdata, flags, reason_code, properties):
    global mqtt_connected
    if reason_code == 0:
        logging.info(f"Connected to {MQTT_BROKER} on topic {root_topic}")
        mqtt_connected = True
    else:
        logging.info(f"Failed to connect to MQTT broker with result code {str(reason_code)}")
        mqtt_connected = False

def message_seen(message_packet):
    message_id = getattr(message_packet, "id")
    if message_id in message_ids:
        return True
    message_ids.append(message_id)
    return False

def on_message(client, userdata, message):
    service_envelope = mqtt_pb2.ServiceEnvelope()
    try:
        service_envelope.ParseFromString(message.payload)
        message_packet = service_envelope.packet
    except Exception as e:
        logging.warning("Error parsing message: %s", str(e))
        return
    
    if message_packet.HasField("encrypted") and not message_packet.HasField("decoded"):
        if not message_seen(message_packet):
            rawmsg = str(message_packet).splitlines()
            rawmsg.pop(3)
            logging.debug(Fore.CYAN + str(rawmsg) + Style.RESET_ALL)
            decode_encrypted(message_packet)
        else:
            logging.debug(Fore.LIGHTBLUE_EX + "Skipping already seen message" + Style.RESET_ALL)
    else:
        logging.debug(Fore.RED + str(message_packet) + Style.RESET_ALL)

def node_db(message_packet, info, pos, env):
    sender = str(getattr(message_packet, "from"))
    with psycopg.connect(db_connection_string) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM nodes WHERE id=%s", (sender,))
        if not cursor.fetchall():
            nid = create_node_id(int(sender))
            cursor.execute("INSERT INTO nodes (id, hexid) VALUES (%s, %s)", (sender, nid))
            logging.info("New node added to DB")

        lastHeard = getattr(message_packet, "rx_time")
        hopcount = getattr(message_packet, "hop_start")
        timestamp = datetime.datetime.fromtimestamp(lastHeard, datetime.UTC)
        check_offline_monitored_node(sender)
        cursor.execute('UPDATE nodes SET online=True, hopcount=%s, LastHeard=%s WHERE id=%s', (hopcount, timestamp, sender))

        if info:
            cursor.execute('UPDATE nodes SET long_name=%s, short_name=%s, hardware=%s, role=%s WHERE id=%s',
                           (info.long_name, info.short_name, info.hw_model, info.role, sender))
        elif pos:
            lat = str(getattr(pos, "latitude_i") / 10000000) if pos.latitude_i else None
            lon = str(getattr(pos, "longitude_i") / 10000000) if pos.longitude_i else None
            alt = str(getattr(pos, "altitude", None))
            if int(alt) > 32000:
                logging.warning("Impossible ALT: %s from: %s", alt, create_node_id(int(sender)))
                alt = None
            cursor.execute('UPDATE nodes SET latitude=%s, longitude=%s, altitude=%s WHERE id=%s', (lat, lon, alt, sender))
        elif env:
            dev = getattr(env, "device_metrics")
            telem = {metric: str(round(getattr(dev, metric, 0), 3)) if getattr(dev, metric, 0) != 0 else None
                     for metric in ["battery_level", "voltage", "channel_utilization", "air_util_tx"]}
            telem["id"] = sender
            if any(telem.values()):
                logging.debug(json.dumps(telem, indent=4))
                cursor.execute('UPDATE nodes SET battery_level=%s, voltage=%s, channel_utilization=%s, air_util_tx=%s WHERE id=%s',
                               (telem["battery_level"], telem["voltage"], telem["channel_utilization"], telem["air_util_tx"], telem["id"]))
                cursor.execute('INSERT INTO telemetry (node, timestamp, battery_level, voltage, channel_utilization, air_util_tx) VALUES (%s, %s, %s, %s, %s, %s)',
                               (telem["id"], timestamp, telem["battery_level"], telem["voltage"], telem["channel_utilization"], telem["air_util_tx"]))
        conn.commit()

def check_database():
    try:
        with psycopg.connect(db_connection_string):
            pass
    except psycopg.Error as e:
        logging.warning(e)
        exit()

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
        logging.error(e)

def create_node_id(node_number):
    return f"!{hex(node_number)[2:]}"

def load_watch():
    global watch
    with open('/app/watch.txt', 'r') as file:
        for line in file:
            id, email, hours = line.strip().split(',')
            watch[id] = (email, float(hours))

def setup():
    global db_connection_string, mqtt_connected
    db_connection_string = f"dbname={db_name} host={db_host} user={db_user} password={db_pass} port={db_port}"
    mqtt_connected = False  # Initialize the MQTT connection status
    check_database()
    setup_tables()
    load_watch()
    cleanup_old()
    schedule.every(1).minutes.do(check_offline)
    schedule.every(2).minutes.do(cleanup_old)


def load_db():
    statement = "SELECT * FROM nodes"
    with psycopg.connect(db_connection_string) as conn:
        with conn.cursor() as cursor:
            cursor.execute(statement)
            rows = cursor.fetchall()
            node_info = {str(row[0]): {desc.name: value for desc, value in zip(cursor.description, row)} for row in rows}
    return node_info

def cleanup_old():
    logging.info("Cleaning DB")
    with psycopg.connect(db_connection_string) as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM telemetry WHERE timestamp < now() - interval '30 days'")
        conn.commit()

def check_offline_monitored_node(id):
    nid = create_node_id(int(id))
    logging.info(nid + " = " + id)
    try:
        if watch[nid]:
            logging.info("Node exists in watched list!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
            with psycopg.connect(db_connection_string) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id, LastHeard FROM nodes WHERE (id=%s AND online=False)", (id,))
                rows = cursor.fetchall()
                if rows:
                    msg = id + ' was offline ' + str(rows)
                    logging.info(msg)
                else:
                    logging.info(id + ' not offline')
    except:
        logging.info("this isnt monitored " + str(watch))




def check_offline():
    load_watch()
    logging.info("Checking for offline nodes")
    node_info = load_db()
    now = datetime.datetime.now(datetime.UTC)
    for i in node_info:
        thisnode = node_info[i]
        id = thisnode['hexid']
        if thisnode['online'] != False:
            timestamp = thisnode['lastheard']
            timegap = now - timestamp
            total_hours = round(timegap.total_seconds() / 3600, 2)
            shortname = thisnode['short_name']
            try:
                email = watch[id][0]
                max_hours = watch[id][1]
                batterylevel = thisnode['battery_level']
                logging.info('Watched node %s %s last seen %s hours ago. Limit %s', id, shortname, total_hours, max_hours)
            except Exception as e:
                #logging.error("An error occurred: %s", e)
                email = None
                max_hours = 6
                #logging.info('Node %s is not watched', shortname)
            if total_hours >= max_hours:
                with psycopg.connect(db_connection_string) as conn:
                    with conn.cursor() as cursor:
                        cursor.execute('UPDATE nodes SET online=False WHERE hexid=%s', (id,))
                    conn.commit()
                if email:
                    logging.warning('Max time exceeded for ID: %s %s, Last Heard (Hours): %s, Max Age: %s - emailing %s from %s',
                                    id, shortname, total_hours, max_hours, email, email_sender)
                    subject = f'Meshtastic node {id} - {shortname} offline'
                    localtimestamp = timestamp.astimezone(ZoneInfo('Pacific/Auckland'))
                    body = f'Node {id} - {shortname} was last seen at {localtimestamp}, {total_hours} hours ago with {batterylevel}% battery'
                    send_email(subject, body, email)

def send_email(subject, body, recipient):
    logging.debug(f"email_sender: {email_sender}, recipient: {recipient}")

    if isinstance(recipient, tuple):
        recipient = recipient[0]

    msg = MIMEText(body)
    msg['Subject'] = str(subject)
    msg['From'] = str(email_sender)
    msg['To'] = str(recipient)
    
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp_server:
            smtp_server.login(email_sender, email_password)
            smtp_server.sendmail(email_sender, recipient, msg.as_string())
        logging.info("Message sent!")
    except Exception as e:
        logging.error("An error occurred: %s", e)

def setup_mqtt():
    global mqtt_connected
    client = mqtt.Client(client_id=f"StatsClient{random.randint(1000, 9999)}", protocol=mqtt.MQTTv5,callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    client.username_pw_set(username=MQTT_USERNAME, password=MQTT_PASSWORD)
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.subscribe(root_topic, qos=0)
    return client

if __name__ == '__main__':
    setup()
    client = setup_mqtt()
    while client.loop() == 0:
        schedule.run_pending()