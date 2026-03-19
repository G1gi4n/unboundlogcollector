import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    import MySQLdb
except ImportError:  # pragma: no cover - exercised only when deps are missing
    MySQLdb = None


DEFAULT_LOG_FILE = "/var/lib/unbound/log/unbound.log"
LOG_PATTERN = re.compile(
    r"\[(?P<unix_ts>\d+)\]\s+"
    r"unbound\[\d+:\d+\]\s+info:\s+"
    r"(?P<client>[0-9A-Fa-f:.]+)\s+"
    r"(?P<domain>\S+)\s+"
    r"(?P<qtype>\S+)\s+"
    r"(?P<qclass>\S+)"
    r"(?:\s+(?P<rcode>\S+))?"
    r"(?:\s+(?P<latency>\d+(?:\.\d+)?))?"
)
LOGGER = logging.getLogger("unboundlogcollector")


@dataclass(frozen=True)
class CollectorConfig:
    log_file: Path
    db_host: str
    db_user: str
    db_password: str
    db_name: str
    db_port: int
    poll_interval: float
    start_from_end: bool

    def db_connect_kwargs(self) -> dict:
        return {
            "host": self.db_host,
            "user": self.db_user,
            "passwd": self.db_password,
            "db": self.db_name,
            "port": self.db_port,
            "charset": "utf8mb4",
        }


@dataclass(frozen=True)
class ParsedLogEntry:
    client_ip: str
    domain: str
    qtype: str
    qclass: str
    rcode: Optional[str]
    latency_ms: Optional[float]
    timestamp: datetime


def env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_config_from_env() -> CollectorConfig:
    return CollectorConfig(
        log_file=Path(os.getenv("UNBOUND_LOG_FILE", DEFAULT_LOG_FILE)),
        db_host=os.getenv("UNBOUND_DB_HOST", "localhost"),
        db_user=os.getenv("UNBOUND_DB_USER", "admin"),
        db_password=os.getenv("UNBOUND_DB_PASSWORD", ""),
        db_name=os.getenv("UNBOUND_DB_NAME", "dns"),
        db_port=int(os.getenv("UNBOUND_DB_PORT", "3306")),
        poll_interval=float(os.getenv("UNBOUND_POLL_INTERVAL", "0.2")),
        start_from_end=env_flag("UNBOUND_START_FROM_END", True),
    )


def parse_log_line(line: str) -> Optional[ParsedLogEntry]:
    match = LOG_PATTERN.search(line)
    if not match:
        return None

    data = match.groupdict()
    latency = data.get("latency")

    return ParsedLogEntry(
        client_ip=data["client"],
        domain=data["domain"],
        qtype=data["qtype"],
        qclass=data["qclass"],
        rcode=data.get("rcode"),
        latency_ms=float(latency) * 1000 if latency else None,
        timestamp=datetime.fromtimestamp(int(data["unix_ts"]), tz=timezone.utc),
    )


def insert_log(cursor, entry: ParsedLogEntry) -> None:
    status = "response" if entry.rcode else "query"
    db_timestamp = entry.timestamp.astimezone(timezone.utc).replace(tzinfo=None)
    cursor.execute(
        """
        INSERT INTO dns_logs (client_ip, domain, qtype, rcode, latency_ms, status, timestamp)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            entry.client_ip,
            entry.domain,
            entry.qtype,
            entry.rcode,
            entry.latency_ms,
            status,
            db_timestamp,
        ),
    )


def insert_client_ip(cursor, client_ip: str) -> None:
    cursor.execute(
        """
        INSERT INTO accounts_clientip (ip_address)
        SELECT %s
        WHERE NOT EXISTS (
            SELECT 1 FROM accounts_clientip WHERE ip_address = %s
        )
        """,
        (client_ip, client_ip),
    )


def connect_to_database(config: CollectorConfig):
    if MySQLdb is None:
        raise RuntimeError(
            "mysqlclient is not installed. Install dependencies from requirements.txt first."
        )

    return MySQLdb.connect(**config.db_connect_kwargs())


def file_was_replaced(handle, path: Path) -> bool:
    try:
        current_path_stat = path.stat()
    except FileNotFoundError:
        return False

    current_handle_stat = os.fstat(handle.fileno())
    same_file = (
        current_path_stat.st_dev == current_handle_stat.st_dev
        and current_path_stat.st_ino == current_handle_stat.st_ino
    )

    if not same_file:
        return True

    return handle.tell() > current_path_stat.st_size


def open_log_file(path: Path, start_from_end: bool):
    handle = path.open("r", encoding="utf-8", errors="replace")
    if start_from_end:
        handle.seek(0, os.SEEK_END)
    return handle


def follow_log(path: Path, poll_interval: float, start_from_end: bool = True):
    handle = open_log_file(path, start_from_end=start_from_end)

    try:
        while True:
            line = handle.readline()
            if line:
                yield line
                continue

            if file_was_replaced(handle, path):
                handle.close()
                handle = open_log_file(path, start_from_end=False)
                LOGGER.info("Reopened rotated log file: %s", path)
                continue

            time.sleep(poll_interval)
    finally:
        handle.close()


def process_entry(db, cursor, entry: ParsedLogEntry) -> None:
    insert_client_ip(cursor, entry.client_ip)
    insert_log(cursor, entry)
    db.commit()


def run_collector(config: CollectorConfig) -> None:
    db = connect_to_database(config)
    cursor = db.cursor()

    try:
        for line in follow_log(
            config.log_file,
            poll_interval=config.poll_interval,
            start_from_end=config.start_from_end,
        ):
            entry = parse_log_line(line)
            if entry is None:
                continue

            try:
                process_entry(db, cursor, entry)
            except Exception:
                try:
                    db.rollback()
                except Exception:  # pragma: no cover - defensive rollback guard
                    LOGGER.exception("Rollback failed after database error.")
                LOGGER.exception(
                    "Failed to persist log entry for client=%s domain=%s",
                    entry.client_ip,
                    entry.domain,
                )
    finally:
        cursor.close()
        db.close()


def configure_logging() -> None:
    logging.basicConfig(
        level=os.getenv("UNBOUND_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main() -> int:
    configure_logging()
    config = load_config_from_env()

    try:
        LOGGER.info(
            "Starting collector for %s (db=%s@%s:%s/%s)",
            config.log_file,
            config.db_user,
            config.db_host,
            config.db_port,
            config.db_name,
        )
        run_collector(config)
    except FileNotFoundError:
        LOGGER.error("Unbound log file not found: %s", config.log_file)
        return 1
    except KeyboardInterrupt:
        LOGGER.info("Collector stopped by user.")
        return 0
    except Exception:
        LOGGER.exception("Collector exited with an unrecoverable error.")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
