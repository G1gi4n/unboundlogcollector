# Unbound Log Collector

Small Python service that tails an Unbound log and writes parsed DNS activity into MySQL.

## What it does

- Follows the Unbound log file continuously.
- Parses query and response lines, including IPv6 clients.
- Inserts new client IPs into `accounts_clientip`.
- Inserts DNS activity into `dns_logs`.
- Reopens the log automatically after rotation or truncation.

## Requirements

- Python 3.10+
- MySQL or MariaDB
- Read access to the Unbound log file

Install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuration

The collector is configured with environment variables.

```bash
export UNBOUND_LOG_FILE=/var/lib/unbound/log/unbound.log
export UNBOUND_DB_HOST=localhost
export UNBOUND_DB_PORT=3306
export UNBOUND_DB_USER=admin
export UNBOUND_DB_PASSWORD=change-me
export UNBOUND_DB_NAME=dns
export UNBOUND_POLL_INTERVAL=0.2
export UNBOUND_START_FROM_END=true
export UNBOUND_VERBOSITY=1
export UNBOUND_LOG_LEVEL=INFO
```

Notes:

- `UNBOUND_START_FROM_END=true` matches the original behavior and skips existing lines already in the log at startup.
- Set `UNBOUND_START_FROM_END=false` if you want to ingest from the beginning of the current file.
- `UNBOUND_VERBOSITY=2` logs each successfully processed raw Unbound log line.
- Timestamps are stored in UTC.

## Database schema

The repository now includes a starter schema in [schema.sql](/Users/giancarloguiao/Desktop/devs/UnboundLogCollector/schema.sql). Apply it before running the collector if you do not already have compatible tables.

```bash
mysql -u root -p dns < schema.sql
```

## Running

```bash
python3 unboundlogcollector.py
```

## Running as a daemon

Use a service manager instead of trying to double-fork the Python process. On a modern Linux host, `systemd` is the correct daemon wrapper.

Files included in this repo:

- Service unit: [deploy/unboundlogcollector.service](/Users/giancarloguiao/Desktop/devs/UnboundLogCollector/deploy/unboundlogcollector.service)
- Environment file template: [deploy/unboundlogcollector.env.example](/Users/giancarloguiao/Desktop/devs/UnboundLogCollector/deploy/unboundlogcollector.env.example)

Suggested setup:

1. Install the project under `/opt/unboundlogcollector` and create a virtualenv:

   ```bash
   sudo mkdir -p /opt/unboundlogcollector
   sudo cp -R . /opt/unboundlogcollector
   cd /opt/unboundlogcollector
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```

2. Create the runtime configuration file:

   ```bash
   sudo mkdir -p /etc/unboundlogcollector
   sudo cp deploy/unboundlogcollector.env.example /etc/unboundlogcollector/unboundlogcollector.env
   sudo chmod 640 /etc/unboundlogcollector/unboundlogcollector.env
   ```

3. Edit `/etc/unboundlogcollector/unboundlogcollector.env` and set the real database credentials and log path.

4. Make sure the service account can read the Unbound log and reach MySQL. The sample unit uses `User=unbound` and `Group=unbound`; change that in the unit if your host uses a different account.

5. Install the service unit:

   ```bash
   sudo cp deploy/unboundlogcollector.service /etc/systemd/system/unboundlogcollector.service
   sudo systemctl daemon-reload
   sudo systemctl enable --now unboundlogcollector
   ```

6. Check service health and logs:

   ```bash
   sudo systemctl status unboundlogcollector
   sudo journalctl -u unboundlogcollector -f
   ```

The collector now handles `SIGTERM` cleanly, which is what `systemd` sends on stop or restart.

## Are environment variables safe for daemon settings?

Yes for non-secret settings, and acceptable for secrets if you keep them in a root-managed environment file with tight permissions.

Recommended:

- Put daemon settings in `/etc/unboundlogcollector/unboundlogcollector.env`.
- Keep the file owned by `root` and mode `0640` or stricter.
- Avoid exporting secrets directly in shell history or inline `systemctl set-environment` commands.

Important caveat:

- Environment variables are not the strongest secret storage. A privileged user can still inspect a running process environment.
- For typical self-managed Linux deployments, a root-owned `EnvironmentFile=` is usually fine.
- If you need stronger isolation, use a dedicated secret store or a separate root-readable credentials file and load it at runtime.

## Testing

The repo uses the standard library `unittest` test suite.

```bash
python3 -m unittest discover -s tests -v
```
