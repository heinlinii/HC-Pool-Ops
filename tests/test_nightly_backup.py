import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location("nightly_backup", Path(__file__).resolve().parents[1] / "scripts/nightly_backup.py")
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)

ENV = {"DATABASE_URL": "postgresql://user:secret@legacy.example/legacy",
       "R2_ENABLED": "true", "R2_ACCOUNT_ID": "account", "R2_ACCESS_KEY_ID": "key",
       "R2_SECRET_ACCESS_KEY": "secret", "R2_BUCKET_NAME": "existing-backups"}


class Body:
    def __init__(self, content):
        self.content = content
        self.closed = False

    def iter_chunks(self, chunk_size):
        yield self.content[:2]
        yield self.content[2:]

    def close(self):
        self.closed = True


class BackupTests(unittest.TestCase):
    def test_rejects_missing_or_non_postgres_database(self):
        for value in ["", "sqlite:///local.db", "postgresql://host/", "postgresql://[bad"]:
            with self.subTest(value=value), self.assertRaises(backup.BackupError):
                backup.database_url({"DATABASE_URL": value})

    def test_disabled_storage_is_failure_before_database_read(self):
        collector = Mock()
        with self.assertRaises(backup.BackupError):
            backup.run_backup({**ENV, "R2_ENABLED": "false"}, collector=collector)
        collector.assert_not_called()

    def test_missing_credentials_are_failure_before_database_read(self):
        collector = Mock()
        with self.assertRaisesRegex(backup.BackupError, "R2_SECRET_ACCESS_KEY"):
            backup.run_backup({**ENV, "R2_SECRET_ACCESS_KEY": ""}, collector=collector)
        collector.assert_not_called()

    def test_verifies_downloaded_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "backup_test.json"
            path.write_bytes(b'{"test": 1}')
            body = Body(path.read_bytes())
            s3 = Mock()
            s3.get_object.return_value = {"Body": body}
            with contextlib.redirect_stdout(io.StringIO()):
                result = backup.upload_to_r2(path, backup.r2_settings(ENV), s3)
            self.assertEqual(result["bytes"], path.stat().st_size)
            self.assertEqual(result["object_key"], "poolops-backups/backup_test.json")
            self.assertTrue(body.closed)
            s3.get_object.assert_called_once_with(Bucket="existing-backups", Key=result["object_key"])

    def test_corrupt_download_fails_even_with_same_size(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "backup_test.json"
            path.write_bytes(b"original")
            s3 = Mock()
            body = Body(b"tampered")
            s3.get_object.return_value = {"Body": body}
            with self.assertRaises(backup.BackupError):
                backup.upload_to_r2(path, backup.r2_settings(ENV), s3)
            self.assertTrue(body.closed)

    def test_upload_errors_propagate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "backup_test.json"
            path.write_text("{}")
            s3 = Mock()
            s3.upload_file.side_effect = RuntimeError("upload denied")
            with self.assertRaises(RuntimeError):
                backup.upload_to_r2(path, backup.r2_settings(ENV), s3)
            s3.get_object.assert_not_called()

    def test_readback_errors_propagate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "backup_test.json"
            path.write_text("{}")
            s3 = Mock()
            s3.get_object.side_effect = RuntimeError("read denied")
            with self.assertRaises(RuntimeError):
                backup.upload_to_r2(path, backup.r2_settings(ENV), s3)

    def test_run_keeps_failed_upload_local_file_without_success(self):
        snapshot = {"timestamp": "test", "source_database": "legacy", "table_counts": {"poolops2_invoices": 1801}}
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(output):
            with self.assertRaises(RuntimeError):
                backup.run_backup(ENV, directory, collector=lambda url: snapshot,
                                  uploader=Mock(side_effect=RuntimeError("offline")))
            self.assertEqual(json.loads((Path(directory) / "backup_test.json").read_text()), snapshot)
        self.assertNotIn('"status": "success"', output.getvalue())

    def test_main_returns_nonzero_and_redacts_sdk_or_connection_error(self):
        stderr = io.StringIO()
        with patch.object(backup, "run_backup", side_effect=RuntimeError(ENV["DATABASE_URL"])), contextlib.redirect_stderr(stderr):
            self.assertEqual(backup.main(), 1)
        self.assertNotIn("secret", stderr.getvalue())
        self.assertNotIn("postgresql", stderr.getvalue())

    def test_main_returns_zero_only_after_verified_run(self):
        with patch.object(backup, "run_backup", return_value={}):
            self.assertEqual(backup.main(), 0)

    def fake_postgres(self, missing=False):
        cursor = Mock()
        cursor.__enter__ = Mock(return_value=cursor)
        cursor.__exit__ = Mock(return_value=False)
        cursor.fetchone.return_value = {"name": "legacy", "captured_at": "2026-10-18"}
        tables = list(backup.REQUIRED_TABLES.values()) + ["other_business_records", "quickbooks_tokens"]
        if missing:
            tables.remove("poolops2_clients")
        included = [t for t in tables if t not in backup.EXCLUDED_TABLES]
        cursor.fetchall.side_effect = [[{"table_name": t} for t in tables]] + [[{"id": i}] for i, _ in enumerate(included)]
        conn = Mock()
        conn.__enter__ = Mock(return_value=conn)
        conn.__exit__ = Mock(return_value=False)
        conn.cursor.return_value = cursor
        connect = Mock(return_value=conn)
        psycopg = types.ModuleType("psycopg")
        psycopg.connect = connect
        psycopg.sql = types.SimpleNamespace(SQL=lambda s: s, Identifier=lambda s: '"' + s + '"')
        rows = types.ModuleType("psycopg.rows")
        rows.dict_row = object()
        return {"psycopg": psycopg, "psycopg.rows": rows}, connect, cursor

    def test_single_readonly_snapshot_includes_invoices_and_other_business_tables(self):
        modules, connect, cursor = self.fake_postgres()
        with patch.dict(sys.modules, modules):
            snapshot = backup.collect_snapshot(ENV["DATABASE_URL"])
        connect.assert_called_once()
        self.assertEqual(cursor.execute.call_args_list[0].args[0], "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        self.assertIn("poolops2_invoices", snapshot["tables"])
        self.assertIn("other_business_records", snapshot["tables"])
        self.assertNotIn("quickbooks_tokens", snapshot["tables"])
        self.assertEqual(snapshot["invoices"], snapshot["tables"]["poolops2_invoices"])
        self.assertEqual(snapshot["clients"], snapshot["tables"]["poolops2_clients"])

    def test_wrong_database_schema_fails_without_export(self):
        modules, connect, cursor = self.fake_postgres(missing=True)
        with patch.dict(sys.modules, modules), self.assertRaisesRegex(backup.BackupError, "poolops2_clients"):
            backup.collect_snapshot(ENV["DATABASE_URL"])
        self.assertEqual(cursor.execute.call_count, 4)


if __name__ == "__main__":
    unittest.main()
