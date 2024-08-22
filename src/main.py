import schedule
import db
import monitor
import meshmqtt
import config


def setup():
    global mqtt_connected
    mqtt_connected = False  # Initialize the MQTT connection status
    if not db.check_db():
        db.create_db()
    db.setup_tables()
    db.cleanup_old()
    if config.testmode:
        schedule.every(1).minutes.do(monitor.check_offline)
        schedule.every(2).minutes.do(db.cleanup_old)
    else:
        schedule.every(15).minutes.do(monitor.check_offline)
        schedule.every(60).minutes.do(db.cleanup_old)


if __name__ == '__main__':
    setup()
    client = meshmqtt.setup_mqtt()
    while client.loop() == 0:
        schedule.run_pending()