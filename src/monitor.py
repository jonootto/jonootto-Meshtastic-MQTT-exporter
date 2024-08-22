import config
import messages
import db
import datetime
from zoneinfo import ZoneInfo
import sendemail
import logs

watch = {}

def check_offline_monitored_node(id):
    nid = messages.create_node_id(int(id))
    output = False
    try:
        if watch[nid]:
            with db.psycopg.connect(db.db_connection_string) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT LastHeard, short_name FROM nodes WHERE (id=%s AND online=False)", (id,))
                row = cursor.fetchone()
                if row:
                    output = True
    except:
        output = False

    if output:
        timestamp = row[0]
        sname = row[1]
        now = datetime.datetime.now(datetime.UTC)
        timegap = now - timestamp
        total_hours = round(timegap.total_seconds() / 3600, 2)
        localtimestamp = timestamp.astimezone(ZoneInfo('Pacific/Auckland'))
        localnow = now.astimezone(ZoneInfo('Pacific/Auckland'))
        msg = f'{nid} - {sname} has come back online at {localnow.strftime(config.timef)} after being offline for {total_hours} hours, since {localtimestamp.strftime(config.timef)}'
        logs.logging.info(msg)
        email = watch[nid][0]
        subject = f'Meshtastic Node {nid} - {sname} has come back online'
        sendemail.send_email(subject, msg, email)

def check_offline():
    load_watch()
    logs.logging.info("Checking for offline nodes")
    node_info = db.load_db()
    now = datetime.datetime.now(datetime.UTC)
    for i in node_info:
        thisnode = node_info[i]
        if thisnode['online'] is not False:
            timestamp = thisnode['lastheard']
            timegap = now - timestamp
            total_hours = round(timegap.total_seconds() / 3600, 2)
            shortname = thisnode['short_name']
            try:
                id = thisnode['hexid']
                email = watch[id][0]
                max_hours = watch[id][1]
                batterylevel = thisnode['battery_level']
                logs.logging.info('Watched node %s %s last seen %s hours ago. Limit %s', id, shortname, total_hours, max_hours)
            except Exception as e:
                #logs.logging.error("An error occurred: %s", e)
                email = None
                max_hours = 6
                #logs.logging.info('Node %s is not watched', shortname)
            if total_hours >= max_hours:
                with db.psycopg.connect(db.db_connection_string) as conn:
                    with conn.cursor() as cursor:
                        cursor.execute('UPDATE nodes SET online=False WHERE hexid=%s', (id,))
                    conn.commit()
                if email:
                    logs.logging.warning('Max time exceeded for ID: %s - %s, Last Heard (Hours): %s, Max Age: %s - emailing %s from %s',
                                    id, shortname, total_hours, max_hours, email, config.email_sender)
                    subject = f'Meshtastic node {id} - {shortname} offline'
                    localtimestamp = timestamp.astimezone(ZoneInfo('Pacific/Auckland'))
                    body = f'Node {id} - {shortname} was last seen at {localtimestamp.strftime(config.timef)}, {total_hours} hours ago with {batterylevel}% battery'
                    sendemail.send_email(subject, body, email)

def load_watch():
    global watch
    with open('/app/watch.txt', 'r') as file:
        for line in file:
            id, email, hours = line.strip().split(',')
            watch[id] = (email, float(hours))