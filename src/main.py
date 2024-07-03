
import paho.mqtt.client as mqtt
from meshtastic import mesh_pb2, mqtt_pb2, portnums_pb2, telemetry_pb2
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import base64
#import sqlite3
from collections import deque
from colorama import Fore, Back, Style
import json
import datetime
import psycopg
from dotenv import load_dotenv
import logging

load_dotenv()
logging.basicConfig(level=logging.INFO)
# Default settings

db_name = "meshtastic"
db_host = "10.1.100.252"
db_user = "postgres"
db_pass = "example"
db_port = "5432"
db_connection_string = ("dbname=" + db_name + " host=" + db_host + " user=" + db_user + " password=" + db_pass + " port=" + db_port)

MQTT_BROKER = "mqtt.meshtastic.org"
MQTT_PORT = 1883
MQTT_USERNAME = "meshdev"
MQTT_PASSWORD = "large4cats"
root_topic = "msh/WLG_915/2/e/"
channel = "LongFast"
key = "1PG7OiApB1nwvP+rz05pAQ=="


padded_key = key.ljust(len(key) + ((4 - (len(key) % 4)) % 4), '=')
replaced_key = padded_key.replace('-', '+').replace('_', '/')
key = replaced_key


message_ids = deque([],200)

def process_message(mp, text_payload, is_encrypted):

    text = {
        "message": text_payload,
        "from": getattr(mp, "from"),
        "id": getattr(mp, "id"),
        "to": getattr(mp, "to")
    }

    #logging.info(text)

def decode_encrypted(message_packet):
    try:
        key_bytes = base64.b64decode(key.encode('ascii'))
        nonce_packet_id = getattr(message_packet, "id").to_bytes(8, "little")
        nonce_from_node = getattr(message_packet, "from").to_bytes(8, "little")
        nonce = nonce_packet_id + nonce_from_node

        cipher = Cipher(algorithms.AES(key_bytes), modes.CTR(nonce), backend=default_backend())
        decryptor = cipher.decryptor()
        decrypted_bytes = decryptor.update(getattr(message_packet, "encrypted")) + decryptor.finalize()

        data = mesh_pb2.Data()
        data.ParseFromString(decrypted_bytes)
        message_packet.decoded.CopyFrom(data)
        info = False
        pos = False
        env = False
        if message_packet.decoded.portnum == portnums_pb2.NODEINFO_APP:
            info = mesh_pb2.User()
            info.ParseFromString(message_packet.decoded.payload)
            #logging.info("NODEINFO_APP")

            #logging.info(info)
        elif message_packet.decoded.portnum == portnums_pb2.POSITION_APP:
            pos = mesh_pb2.Position()
            pos.ParseFromString(message_packet.decoded.payload)
            #logging.info("POSITION_APP")
            #logging.info(pos)

        elif message_packet.decoded.portnum == portnums_pb2.TELEMETRY_APP:
            env = telemetry_pb2.Telemetry()
            env.ParseFromString(message_packet.decoded.payload)
            #logging.info(Fore.LIGHTGREEN_EX + "TELEMETRY_APP" + Style.RESET_ALL)     
            #logging.info(env)

        #elif message_packet.decoded.portnum == portnums_pb2.TEXT_MESSAGE_APP:
            #text_payload = message_packet.decoded.payload.decode("utf-8")
            #is_encrypted = True
            #process_message(message_packet, text_payload, is_encrypted)
            #logging.info("TEXT_MESSAGE_APP")
            #logging.info(f"{text_payload}")

    except Exception as e:
        logging.info(f"Decryption failed: {str(e)}")
    node_db(message_packet,info,pos,env)

def on_connect(client, userdata, flags, rc, properties):
    if rc == 0:
        logging.info(f"Connected to {MQTT_BROKER} on topic {channel}")
    else:
        logging.info(f"Failed to connect to MQTT broker with result code {str(rc)}")


def message_seen(message_packet):
    id = getattr(message_packet, "id")
    try: 
        message_ids.index(id)
        return True
    except:
        message_ids.append(id)
        return False



def on_message(client, userdata, msg):
    service_envelope = mqtt_pb2.ServiceEnvelope()
    try:
        service_envelope.ParseFromString(msg.payload)
        # logging.info(service_envelope)
        message_packet = service_envelope.packet
    except Exception as e:
        logging.info(f"Error parsing message: {str(e)}")
        return
    
    if message_packet.HasField("encrypted") and not message_packet.HasField("decoded"):
        if not message_seen(message_packet):
            #logging.info(Fore.CYAN + str(message_packet) + Style.RESET_ALL)
            decode_encrypted(message_packet)
       #else:
            #logging.info(Fore.RED + "Skipping already seen message" + Style.RESET_ALL)


def node_db(message_packet,info,pos,env):
    sender = str(getattr(message_packet, "from"))
    conn = psycopg.connect(db_connection_string)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM nodes WHERE id=%s",(sender,))
    nodes = cursor.fetchall()
    if len(nodes) == 0:
        #New node
        nid = create_node_id(int(sender))
        cursor.execute("INSERT INTO nodes (id, hexid) VALUES (%s,%s)",(sender,nid))
        logging.info("New node added to DB")
        
    #add info
    lastHeard = (getattr(message_packet, "rx_time"))
    timestamp = datetime.datetime.fromtimestamp(lastHeard,datetime.UTC)
    cursor.execute('UPDATE nodes SET LastHeard=%s WHERE id=%s', (timestamp, sender))

    if info:
        long_name = str(getattr(info, "long_name"))
        short_name = str(getattr(info, "short_name"))
        hw_model = str(getattr(info, "hw_model"))
        role = str(getattr(info, "role"))
        cursor.execute('UPDATE nodes SET long_name=%s, short_name=%s, hardware=%s, role=%s WHERE id = %s', (long_name, short_name, hw_model ,role , sender))

    elif pos:
        try:
            lat = str(getattr(pos, "latitude_i")/10000000)
            lon = str(getattr(pos, "longitude_i")/10000000)
        except:
            lat = None
            lon = None
        alt = str(getattr(pos, "altitude",None))
        if int(alt) > 32000:
            logging.info("Impossible ALT")
            alt = None
        cursor.execute('UPDATE nodes SET latitude=%s, longitude=%s, altitude=%s WHERE id=%s', (lat, lon, alt, sender))   

    elif env:
        dev = getattr(env, "device_metrics")
        telem = {
            "battery_level": None,
            "voltage": None,
            "channel_utilization": None,
            "air_util_tx": None
        }
        value = False
        for metric in telem.keys():

            newval = (getattr(dev, metric))
            try:
                nullcheck = int(newval*100)
                if nullcheck == 0:
                    output = None
                else:
                    output = str(round(newval,3))
                    value = True
            except:
                output = None
            telem.update({metric:output})
        telem["id"] = sender
        if value:
            logging.info(json.dumps(telem,indent=4))
            cursor.execute('UPDATE nodes SET battery_level=%s, voltage=%s, channel_utilization=%s, air_util_tx=%s WHERE id = %s', (telem["battery_level"], telem["voltage"], telem["channel_utilization"], telem["air_util_tx"], telem["id"])) 
            cursor.execute('INSERT INTO telemetry (node, timestamp, battery_level, voltage, channel_utilization, air_util_tx) VALUES (%s,%s,%s,%s,%s,%s)',(telem["id"],timestamp,telem["battery_level"],telem["voltage"], telem["channel_utilization"], telem["air_util_tx"]))


    conn.commit()
    conn.close()
    return

def check_database():
    conn = None
    try:
        conn = psycopg.connect(db_connection_string)
    except psycopg.Error as e:
        logging.info(e)
        exit()
    finally:
        if conn:
            conn.close()

def setup_tables():
    statements = ["""CREATE TABLE IF NOT EXISTS nodes (
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
                LastHeard TIMESTAMPTZ
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
                cursor = conn.cursor()
                cursor.execute(statement)
                conn.commit()
    except psycopg.Error as e:
        logging.info(e)

def create_node_id(node_number):
    return f"!{hex(node_number)[2:]}"

def setup():
    check_database()
    setup_tables()

def loadDB():
    statement = "SELECT * FROM nodes"# WHERE id = 2990211348"
    with psycopg.connect(db_connection_string) as conn:
        cursor = conn.cursor()
        cursor.execute(statement)
        r = [dict((cursor.description[i][0], value) \
            for i, value in enumerate(row)) for row in cursor.fetchall()]
    node_info = {}

    for item in r:
        nextnode = {}
        for data in item:
            if data != "id":
                nextnode.update({data:item[data]})
        node_info.update({str(item["id"]):nextnode})
    logging.info(json.dumps(node_info["2990211348"],indent=4))
    logging.info("loaded db")
    return node_info

def publishMetrics():
    node_info = loadDB(db)

if __name__ == '__main__':
    setup()


    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.username_pw_set(username=MQTT_USERNAME, password=MQTT_PASSWORD)
    client.connect(MQTT_BROKER, MQTT_PORT, 60)

    client.on_message = on_message

    subscribe_topic = f"{root_topic}{channel}/#"

    client.subscribe(subscribe_topic, 0)
    x = 0
    while client.loop() == 0:
        x += 1
        if x == 10:
            #publishMetrics()
            x=0
        pass
