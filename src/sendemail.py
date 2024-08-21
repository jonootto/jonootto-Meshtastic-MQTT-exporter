import smtplib
from email.mime.text import MIMEText
import logs 
import config 


def send_email(subject, body, recipient):

    if isinstance(recipient, tuple):
        recipient = recipient[0]

    msg = MIMEText(body)
    msg['Subject'] = str(subject)
    msg['From'] = str(config.email_sender)
    msg['To'] = str(recipient)
    
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp_server:
            if not config.testmode:
                smtp_server.login(config.email_sender, config.email_password)
                smtp_server.sendmail(config.email_sender, recipient, msg.as_string())
            else:
                logs.logging.info('Simulated Message %s sent: %s',subject, body)
    except Exception as e:
        logs.logging.error("An error occurred: %s", e)