
import paho.mqtt.client as mqtt
from meshtastic import mesh_pb2, mqtt_pb2, portnums_pb2, telemetry_pb2
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import base64
import random
import sqlite3
from collections import deque
from colorama import Fore, Back, Style

# Default settings
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

#broadcast_id = 4294967295
# Convert hex to int and remove '!'
#node_number = int('abcd', 16)
db = "node.db"

message_ids = deque([],50)

def process_message(mp, text_payload, is_encrypted):

    text = {
        "message": text_payload,
        "from": getattr(mp, "from"),
        "id": getattr(mp, "id"),
        "to": getattr(mp, "to")
    }

    #print(text)

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
        node_db(message_packet,db)

        if message_packet.decoded.portnum == portnums_pb2.TEXT_MESSAGE_APP:
            text_payload = message_packet.decoded.payload.decode("utf-8")
            is_encrypted = True
            process_message(message_packet, text_payload, is_encrypted)
            print("TEXT_MESSAGE_APP")
            print(f"{text_payload}")


        elif message_packet.decoded.portnum == portnums_pb2.NODEINFO_APP:
            info = mesh_pb2.User()
            info.ParseFromString(message_packet.decoded.payload)
            print("NODEINFO_APP")

            print(info)
        elif message_packet.decoded.portnum == portnums_pb2.POSITION_APP:
            pos = mesh_pb2.Position()
            pos.ParseFromString(message_packet.decoded.payload)
            print("POSITION_APP")
            print(pos)

        elif message_packet.decoded.portnum == portnums_pb2.TELEMETRY_APP:
            env = telemetry_pb2.Telemetry()
            env.ParseFromString(message_packet.decoded.payload)
            print("TELEMETRY_APP")     
            print(env)
    except Exception as e:
        print(f"Decryption failed: {str(e)}")

def on_connect(client, userdata, flags, rc, properties):
    if rc == 0:
        print(f"Connected to {MQTT_BROKER} on topic {channel}")
    else:
        print(f"Failed to connect to MQTT broker with result code {str(rc)}")




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
        # print(service_envelope)
        message_packet = service_envelope.packet
    except Exception as e:
        print(f"Error parsing message: {str(e)}")
        return
    
    if message_packet.HasField("encrypted") and not message_packet.HasField("decoded"):
        if not message_seen(message_packet):
            print(Fore.CYAN + str(message_packet) + Style.RESET_ALL)
            decode_encrypted(message_packet)
        else:
            print(Fore.RED + "Skipping already seen message" + Style.RESET_ALL)




def node_db(message_packet,filename):
    sender = str(getattr(message_packet, "from"))
    conn = sqlite3.connect(filename)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM nodes WHERE id = '" + sender + "'")
    nodes = cursor.fetchall()
    if len(nodes) == 0:
        #New node
        cursor.execute("INSERT INTO nodes (id) VALUES ('"+ sender + "')")
        print("New node added to DB")
        conn.commit()
    conn.close()
    return

def create_database(filename):
    conn = None
    try:
        conn = sqlite3.connect(filename)
        print(sqlite3.sqlite_version)
    except sqlite3.Error as e:
        print(e)
    finally:
        if conn:
            conn.close()

def setup_tables(filename):
    sql_statements = [ 
        """CREATE TABLE IF NOT EXISTS nodes (
                id INTEGER PRIMARY KEY, 
                long_name text,
                short_name text,
                hardware text,
                latitude REAL,
                longitude REAL,
                altitude INTEGER,
                battery INTEGER,
                voltage REAL,
                chutil REAL,
                txutil REAL,
                LastHeard INTEGER,
                begin_date TEXT, 
                end_date TEXT
        );"""]
    try:
        with sqlite3.connect(filename) as conn:
            cursor = conn.cursor()
            for statement in sql_statements:
                cursor.execute(statement)
            
            conn.commit()
    except sqlite3.Error as e:
        print(e)



def setup():
    create_database(db)
    setup_tables(db)

setup()

if __name__ == '__main__':

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.username_pw_set(username=MQTT_USERNAME, password=MQTT_PASSWORD)
    client.connect(MQTT_BROKER, MQTT_PORT, 60)

    client.on_message = on_message

    subscribe_topic = f"{root_topic}{channel}/#"

    client.subscribe(subscribe_topic, 0)

    while client.loop() == 0:
        pass