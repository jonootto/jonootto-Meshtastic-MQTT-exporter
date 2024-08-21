import schedule
import db
import monitor
import meshmqtt


def setup():
    global mqtt_connected
    mqtt_connected = False  # Initialize the MQTT connection status
    db.check_database()
    db.setup_tables()
    db.cleanup_old()
    schedule.every(1).minutes.do(monitor.check_offline)
    schedule.every(2).minutes.do(db.cleanup_old)


if __name__ == '__main__':
    setup()
    client = meshmqtt.setup_mqtt()
    while client.loop() == 0:
        schedule.run_pending()