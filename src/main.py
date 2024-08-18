
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
import yaml
import smtplib
from email.mime.text import MIMEText

load_dotenv()
FORMAT = '%(levelname)s: %(asctime)s - %(message)s'

# Default settings

db_name = os.environ["DBNAME"]
db_host = os.environ["DBHOST"]
db_user = os.environ["DBUSER"]
db_pass = os.environ["DBPASS"]
db_port = os.environ["DBPORT"]
email_password = os.environ["EPASSWORD"]
email_sender = os.environ["ESENDER"]
db_connection_string = ("dbname=" + db_name + " host=" + db_host + " user=" + db_user + " password=" + db_pass + " port=" + db_port)

llevel = logging.INFO
#llevel = logging.DEBUG

logging.basicConfig(level=llevel,format=FORMAT,datefmt='%H:%M:%S')

timestamptz_format = "%Y-%m-%d %H:%M:%S%z"
watch = {}

MQTT_BROKER = "mqtt.meshtastic.org"
MQTT_PORT = 1883
MQTT_USERNAME = "meshdev"
MQTT_PASSWORD = "large4cats"
root_topic = "msh/WLG_915/2/e/#"
key = "1PG7OiApB1nwvP+rz05pAQ=="

padded_key = key.ljust(len(key) + ((4 - (len(key) % 4)) % 4), '=')
replaced_key = padded_key.replace('-', '+').replace('_', '/')
key = replaced_key

message_ids = deque([],200)
message_types=portnums_pb2.PortNum.items()

def process_message(mp, text_payload, is_encrypted):

    text = {
        "message": text_payload,
        "from": getattr(mp, "from"),
        "id": getattr(mp, "id"),
        "to": getattr(mp, "to")
    }

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
            logging.debug("NODEINFO_APP")
            logging.debug(info)

        elif message_packet.decoded.portnum == portnums_pb2.POSITION_APP:
            pos = mesh_pb2.Position()
            pos.ParseFromString(message_packet.decoded.payload)
            logging.debug("POSITION_APP")
            logging.debug(pos)

        elif message_packet.decoded.portnum == portnums_pb2.TELEMETRY_APP:
            env = telemetry_pb2.Telemetry()
            env.ParseFromString(message_packet.decoded.payload)
            #logging.info(Fore.LIGHTGREEN_EX + "TELEMETRY_APP" + Style.RESET_ALL)     
            #logging.info(env)

        elif message_packet.decoded.portnum == portnums_pb2.TEXT_MESSAGE_APP:
            text_payload = message_packet.decoded.payload.decode("utf-8")
            is_encrypted = True
            process_message(message_packet, text_payload, is_encrypted)
            logging.info("TEXT_MESSAGE_APP")
            logging.info(f"{text_payload}")
        #elif message_packet.decoded.portnum == portnums_pb2.NEIGHBORINFO_APP:
            #nei = 
        else:
            loc = (next((i for i, v in enumerate(message_types) if v[1] == message_packet.decoded.portnum), None))
            type = message_types[loc][0]
            logging.warning(Fore.RED+"Unknown App " + str(message_packet.decoded.portnum) + " " + type + Style.RESET_ALL)
            
            #text_payload = message_packet.decoded.payload.decode("utf-8")
            #is_encrypted = True
            #process_message(message_packet, text_payload, is_encrypted)
            #logging.warning(text_payload)

    except Exception as e:
        logging.warning(f"Decryption failed: {str(e)}")
    node_db(message_packet,info,pos,env)

def on_connect(client, userdata, flags, rc, properties):
    if rc == 0:
        logging.info(f"Connected to {MQTT_BROKER} on topic {root_topic}")
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
        message_packet = service_envelope.packet
    except Exception as e:
        logging.warning(f"Error parsing message: {str(e)}")
        return
    
    if message_packet.HasField("encrypted") and not message_packet.HasField("decoded"):
        if not message_seen(message_packet):
            rawmsg = str(message_packet).splitlines()
            rawmsg.pop(3)
            #parsedmsg = json.dumps(rawmsg,indent=4)
            logging.debug(Fore.CYAN + str(rawmsg) + Style.RESET_ALL)
            decode_encrypted(message_packet)
        else:
            logging.debug(Fore.LIGHTBLUE_EX + "Skipping already seen message" + Style.RESET_ALL)
    else:
        logging.debug(Fore.RED + str(message_packet) + Style.RESET_ALL)
    

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
    hopcount = (getattr(message_packet, "hop_start"))
    timestamp = datetime.datetime.fromtimestamp(lastHeard,datetime.UTC)
    cursor.execute('UPDATE nodes SET online=True, hopcount=%s, LastHeard=%s WHERE id=%s', (hopcount, timestamp, sender))

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
            logging.warning("Impossible ALT: " + alt + " from : " + str(create_node_id(int(sender))))
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
            logging.debug(json.dumps(telem,indent=4))
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
        logging.warning(e)
        exit()
    finally:
        if conn:
            conn.close()

def setup_tables():
    #logging.warn("setup tables")
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
                cursor = conn.cursor()
                cursor.execute(statement)
                conn.commit()
    except psycopg.Error as e:
        logging.error(e)

def create_node_id(node_number):
    return f"!{hex(node_number)[2:]}"

def load_watch():
    with open('/app/watch.txt', 'r') as file:
        for line in file:
            # Split the line by comma and strip any surrounding whitespace/newline characters
            id, email, hours = line.strip().split(',')
            # Append the tuple to the data list
            watch[id] = (email, float(hours))
    #email, hours = watch['!1fa0635c']
    #logging.warning(f"ID: {'!1fa0635c'}, Email: {email}, Time: {hours}")

def setup():
    check_database()
    setup_tables()
    load_watch()
    checkOffline()

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
    #logging.info(json.dumps(node_info["2990211348"],indent=4))
    #logging.debug("loaded db")
    return node_info

def cleanupOld():
    logging.info("Cleaning DB")
    with psycopg.connect(db_connection_string) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM telemetry WHERE timestamp < now() - interval '30 days'")
        conn.commit()



def checkOffline():
    logging.info("Checking for offline nodes")
    node_info = loadDB()
    now = datetime.datetime.now(datetime.UTC)
    for i in node_info:
        if node_info[i]['online'] != False:
            id = node_info[i]['hexid']
            timestamp = node_info[i]['lastheard']
            timegap = now - timestamp
            total_hours = round(timegap.total_seconds() / 3600,2)
            try:
                email = watch[id][0]
                max_hours = watch[id][1]
                shortname = node_info[i]['short_name']
                batterylevel = node_info[i]['battery_level']
                logging.info('Watched node %s %s last seen %s hours ago',id, shortname,total_hours)
            except:
                #NO MATCH
                email = None
                max_hours = 6

            if total_hours >= max_hours:
                with psycopg.connect(db_connection_string) as conn:
                    cursor = conn.cursor()
                    cursor.execute('UPDATE nodes SET online=False WHERE hexid=%s',(id,))
                    conn.commit()

                #write to db
                if email:
                    logging.warning('Max time exceeded for ID: %s %s, Last Heard (Hours): %s, Max Age: %s - emailing %s from %s', id, shortname, total_hours, max_hours, email, email_sender)
                    subject = 'Meshtastic node %s - %s offline' % (id, shortname)
                    localtimestamp = timestamp.astimezone(ZoneInfo('Pacific/Auckland'))
                    body = 'Node %s - %s was last seen at %s, %s hours ago with %s percent battery' % (id,shortname, localtimestamp, total_hours, batterylevel)
                    #send email
                    send_email(subject,body,email)

def send_email(subject, body, recipient):
    # Debugging: Check the types of the inputs
    logging.debug(f"email_sender: {email_sender}, type: {type(email_sender)}")
    logging.debug(f"recipient: {recipient}, type: {type(recipient)}")

    # Ensure recipient is a string and not a tuple
    if isinstance(recipient, tuple):
        recipient = recipient[0]

    # Create MIMEText object
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
        logging.error(f"An error occurred: {e}")



if __name__ == '__main__':
    setup()

    id = "StatsClient" + str(random.randint(1000,9999))
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=id, userdata=None,protocol=mqtt.MQTTv5)
    client.on_connect = on_connect
    client.username_pw_set(username=MQTT_USERNAME, password=MQTT_PASSWORD)
    client.connect(MQTT_BROKER, MQTT_PORT, 60)

    client.on_message = on_message


    client.subscribe(root_topic, 0)
    x = 0
    y = 0
    while client.loop() == 0:
        x += 1
        y +=1
        if x == 100:
            #publishMetrics()
            checkOffline()
            x = 0
        if y == 1000:
            cleanupOld()

            y = 0
        pass