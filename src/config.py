import os
from dotenv import load_dotenv

load_dotenv()
# Environment Variables
db_name = os.environ["DBNAME"]
db_host = os.environ["DBHOST"]
db_user = os.environ["DBUSER"]
db_pass = os.environ["DBPASS"]
db_port = os.environ["DBPORT"]
try:
    testmode = bool(os.environ["TESTMODE"])
except KeyError:
    testmode = False
email_password = os.environ["EPASSWORD"]
email_sender = os.environ["ESENDER"]


# MQTT Configurations
MQTT_BROKER = "mqtt.meshtastic.org"
MQTT_PORT = 1883
MQTT_USERNAME = "meshdev"
# trunk-ignore(bandit/B105)
MQTT_PASSWORD = "large4cats"
root_topic = "msh/WLG_915/2/e/#"
timef = ("%H:%M:%S %d-%m-%Y")

# Encryption Key
key = "1PG7OiApB1nwvP+rz05pAQ==".replace('-', '+').replace('_', '/')
padded_key = key.ljust(len(key) + ((4 - (len(key) % 4)) % 4), '=')