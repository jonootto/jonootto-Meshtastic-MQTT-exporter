import paho.mqtt.client as mqtt
import random
import config
import logs
from meshtastic import mqtt_pb2
import messages

def setup_mqtt():
    global mqtt_connected
    # trunk-ignore(bandit/B311)
    client = mqtt.Client(client_id=f"StatsClient{random.randint(1000, 9999)}", protocol=mqtt.MQTTv5,callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    client.username_pw_set(username=config.MQTT_USERNAME, password=config.MQTT_PASSWORD)
    client.connect(config.MQTT_BROKER, config.MQTT_PORT, 30)
    client.subscribe(config.root_topic, qos=0)
    return client


def on_connect(client, userdata, flags, reason_code, properties):
    global mqtt_connected
    if reason_code == 0:
        logs.logging.info(f"Connected to {config.MQTT_BROKER} on topic {config.root_topic}")
        mqtt_connected = True
    else:
        logs.logging.info(f"Failed to connect to MQTT broker with result code {str(reason_code)}")
        mqtt_connected = False


def on_message(client, userdata, message):
    mqtt_node = message.topic.rpartition('/')[-1]
    #logs.logging.debug(mqtt_node)
    service_envelope = mqtt_pb2.ServiceEnvelope()
    try:
        service_envelope.ParseFromString(message.payload)
        message_packet = service_envelope.packet
    except Exception as e:
        logs.logging.warning("Error parsing message: %s", str(e))
        return
    if message_packet.HasField("encrypted") and not message_packet.HasField("decoded"):
        if not messages.message_seen(message_packet,mqtt_node):
            rawmsg = str(message_packet).splitlines()
            rawmsg.pop(3)
            logs.logging.debug(logs.Fore.CYAN + str(rawmsg) + logs.Style.RESET_ALL)
            messages.decode_encrypted(message_packet)
        else:
            #logs.logging.debug(logs.Fore.LIGHTBLUE_EX + "Skipping already seen message" + logs.Style.RESET_ALL)
            pass
    else:
        #logs.logging.debug(logs.Fore.RED + str(message_packet) + logs.Style.RESET_ALL)
        pass
