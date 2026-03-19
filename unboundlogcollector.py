import time
from datetime import datetime
import re
import MySQLdb
from django.utils import timezone


# ----------------------
# Configuration
# ----------------------
LOG_FILE = "/var/lib/unbound/log/unbound.log"

DB_CONFIG = {
    'host': 'localhost',
    'user': 'admin',
    'passwd': 'dnsserverk0to',
    'db': 'dns'
}

# ----------------------
# Regex pattern for your log format
# ----------------------
LOG_PATTERN = re.compile(
    r'\[(?P<unix_ts>\d+)\]\s+'             # capture timestamp in brackets
    r'unbound\[\d+:\d+\]\s+info:\s+'
    r'(?P<client>\d+\.\d+\.\d+\.\d+)\s+'  # client IP
    r'(?P<domain>\S+)\s+'                  # domain
    r'(?P<qtype>\S+)\s+'                   # query type
    r'(?P<class>\S+)'                      # class
    r'(?:\s+(?P<rcode>\S+))?'              # optional response code
    r'(?:\s+(?P<latency>\d+\.\d+))?'       # optional latency
)

# ----------------------
# Insert into MySQL
# ----------------------
def insert_log(cursor, client, domain, qtype, rcode, latency, timestamp):
    latency_ms = float(latency)*1000 if latency else None
    # Determine status: 'response' if rcode exists, otherwise 'query'
    status = 'response' if rcode else 'query'

    cursor.execute("""
        INSERT INTO dns_logs (client_ip, domain, qtype, rcode, latency_ms, status, timestamp)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
    """, (client, domain, qtype, rcode, latency_ms, status, timestamp))


def insert_clientip(cursor, client_ip):
    cursor.execute("""
        INSERT INTO accounts_clientip (ip_address)
        SELECT %s
        WHERE NOT EXISTS (
            SELECT 1 FROM accounts_clientip WHERE ip_address = %s
        )
    """, (client_ip, client_ip))
# ----------------------
# Main tail loop
# ----------------------
def main():
    db = MySQLdb.connect(**DB_CONFIG)
    cursor = db.cursor()

    with open(LOG_FILE, 'r') as f:
        f.seek(0, 2)  # Go to EOF
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.2)
                continue

            match = LOG_PATTERN.search(line)
            if match:
                data = match.groupdict()


                timestamp = timezone.make_aware(datetime.fromtimestamp(int(data['unix_ts'])),timezone=timezone.UTC)

                insert_clientip(cursor, data['client'])

                insert_log(
                    cursor,
                    data['client'],
                    data['domain'],
                    data['qtype'],
                    data.get('rcode'),
                    data.get('latency'),
                    timestamp
                )
                db.commit()

if __name__ == "__main__":
    main()
