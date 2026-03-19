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
export UNBOUND_LOG_LEVEL=INFO
```

Notes:

- `UNBOUND_START_FROM_END=true` matches the original behavior and skips existing lines already in the log at startup.
- Set `UNBOUND_START_FROM_END=false` if you want to ingest from the beginning of the current file.
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

## Testing

The repo uses the standard library `unittest` test suite.

```bash
python3 -m unittest discover -s tests -v
```
