import os
import tempfile
import unittest
from datetime import datetime, timezone
from threading import Event
from unittest import mock

import unboundlogcollector as collector


class ParseLogLineTests(unittest.TestCase):
    def test_parse_response_line(self):
        line = "[1710000000] unbound[123:0] info: 192.168.1.20 example.com A IN NOERROR 0.123"

        entry = collector.parse_log_line(line)

        self.assertIsNotNone(entry)
        self.assertEqual(entry.client_ip, "192.168.1.20")
        self.assertEqual(entry.domain, "example.com")
        self.assertEqual(entry.qtype, "A")
        self.assertEqual(entry.qclass, "IN")
        self.assertEqual(entry.rcode, "NOERROR")
        self.assertEqual(entry.latency_ms, 123.0)
        self.assertEqual(
            entry.timestamp,
            datetime.fromtimestamp(1710000000, tz=timezone.utc),
        )

    def test_parse_query_line_without_response_fields(self):
        line = "[1710000000] unbound[123:0] info: 192.168.1.20 example.net AAAA IN"

        entry = collector.parse_log_line(line)

        self.assertIsNotNone(entry)
        self.assertIsNone(entry.rcode)
        self.assertIsNone(entry.latency_ms)

    def test_parse_ipv6_client(self):
        line = "[1710000000] unbound[123:0] info: 2001:db8::1 example.org PTR IN NXDOMAIN 0.050"

        entry = collector.parse_log_line(line)

        self.assertIsNotNone(entry)
        self.assertEqual(entry.client_ip, "2001:db8::1")

    def test_unmatched_line_returns_none(self):
        self.assertIsNone(collector.parse_log_line("not an unbound log line"))


class ConfigTests(unittest.TestCase):
    @mock.patch.dict(
        os.environ,
        {
            "UNBOUND_LOG_FILE": "/tmp/unbound.log",
            "UNBOUND_DB_HOST": "db",
            "UNBOUND_DB_PORT": "3307",
            "UNBOUND_DB_USER": "dnsuser",
            "UNBOUND_DB_PASSWORD": "secret",
            "UNBOUND_DB_NAME": "dnslogs",
            "UNBOUND_DB_TIMEZONE": "Asia/Manila",
            "UNBOUND_POLL_INTERVAL": "0.5",
            "UNBOUND_START_FROM_END": "false",
            "UNBOUND_VERBOSITY": "2",
        },
        clear=True,
    )
    def test_load_config_from_env(self):
        config = collector.load_config_from_env()

        self.assertEqual(str(config.log_file), "/tmp/unbound.log")
        self.assertEqual(config.db_host, "db")
        self.assertEqual(config.db_port, 3307)
        self.assertEqual(config.db_user, "dnsuser")
        self.assertEqual(config.db_password, "secret")
        self.assertEqual(config.db_name, "dnslogs")
        self.assertEqual(config.db_timezone, "Asia/Manila")
        self.assertEqual(config.poll_interval, 0.5)
        self.assertFalse(config.start_from_end)
        self.assertEqual(config.verbosity, 2)


class PersistenceTests(unittest.TestCase):
    def test_to_database_timestamp_uses_named_timezone(self):
        db_timestamp = collector.to_database_timestamp(
            datetime(2024, 3, 9, 16, 0, tzinfo=timezone.utc),
            "Asia/Manila",
        )

        self.assertEqual(db_timestamp, datetime(2024, 3, 10, 0, 0))

    def test_insert_log_marks_query_without_rcode(self):
        cursor = mock.Mock()
        entry = collector.ParsedLogEntry(
            client_ip="192.168.1.20",
            domain="example.com",
            qtype="A",
            qclass="IN",
            rcode=None,
            latency_ms=None,
            timestamp=datetime(2024, 3, 9, 16, 0, tzinfo=timezone.utc),
        )

        collector.insert_log(cursor, entry, "Asia/Manila")

        execute_args = cursor.execute.call_args.args
        params = execute_args[1]
        self.assertEqual(params[0], "192.168.1.20")
        self.assertEqual(params[1], "example.com")
        self.assertEqual(params[2], "A")
        self.assertIsNone(params[3])
        self.assertIsNone(params[4])
        self.assertEqual(params[5], "query")
        self.assertEqual(params[6], datetime(2024, 3, 10, 0, 0))

    def test_process_entry_commits_on_success(self):
        db = mock.Mock()
        cursor = mock.Mock()
        config = collector.CollectorConfig(
            log_file=collector.Path("/tmp/unbound.log"),
            db_host="localhost",
            db_user="admin",
            db_password="secret",
            db_name="dns",
            db_port=3306,
            db_timezone="Asia/Manila",
            poll_interval=0.2,
            start_from_end=True,
            verbosity=1,
        )
        entry = collector.ParsedLogEntry(
            client_ip="192.168.1.20",
            domain="example.com",
            qtype="A",
            qclass="IN",
            rcode="NOERROR",
            latency_ms=12.0,
            timestamp=datetime(2024, 3, 9, 16, 0, tzinfo=timezone.utc),
        )

        collector.process_entry(db, cursor, entry, config)

        self.assertEqual(cursor.execute.call_count, 2)
        db.commit.assert_called_once()


class DaemonBehaviorTests(unittest.TestCase):
    def test_follow_log_stops_when_stop_event_is_set(self):
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8") as handle:
            stop_event = Event()
            stop_event.set()

            lines = list(
                collector.follow_log(
                    collector.Path(handle.name),
                    poll_interval=0.01,
                    stop_event=stop_event,
                    start_from_end=False,
                )
            )

        self.assertEqual(lines, [])

    def test_log_processed_line_at_verbosity_two(self):
        config = collector.CollectorConfig(
            log_file=collector.Path("/tmp/unbound.log"),
            db_host="localhost",
            db_user="admin",
            db_password="secret",
            db_name="dns",
            db_port=3306,
            db_timezone="system",
            poll_interval=0.2,
            start_from_end=True,
            verbosity=2,
        )

        with mock.patch.object(collector.LOGGER, "info") as mock_info:
            collector.log_processed_line(
                config,
                "[1710000000] unbound[123:0] info: 192.168.1.20 example.com A IN\n",
            )

        mock_info.assert_called_once_with(
            "Processed log line: %s",
            "[1710000000] unbound[123:0] info: 192.168.1.20 example.com A IN",
        )

    def test_log_processed_line_is_silent_below_verbosity_two(self):
        config = collector.CollectorConfig(
            log_file=collector.Path("/tmp/unbound.log"),
            db_host="localhost",
            db_user="admin",
            db_password="secret",
            db_name="dns",
            db_port=3306,
            db_timezone="system",
            poll_interval=0.2,
            start_from_end=True,
            verbosity=1,
        )

        with mock.patch.object(collector.LOGGER, "info") as mock_info:
            collector.log_processed_line(
                config,
                "[1710000000] unbound[123:0] info: 192.168.1.20 example.com A IN\n",
            )

        mock_info.assert_not_called()


if __name__ == "__main__":
    unittest.main()
