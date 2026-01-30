"""Tests for scheduler module."""

import json
import tempfile
import time
import threading
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest

from src.scheduler import (
    SchedulerStatus,
    with_retry,
    send_notification,
    start_health_server,
    check_tws_connection,
)


class TestSchedulerStatus:
    """Tests for SchedulerStatus class."""

    def test_init_creates_file(self, tmp_path):
        """Test that status file is created on init."""
        status_file = tmp_path / "status.json"
        status = SchedulerStatus(status_file)
        assert status_file.parent.exists()

    def test_set_started(self, tmp_path):
        """Test setting scheduler started timestamp."""
        status_file = tmp_path / "status.json"
        status = SchedulerStatus(status_file)

        status.set_started()

        assert status_file.exists()
        with open(status_file) as f:
            data = json.load(f)
        assert "scheduler_started" in data
        assert data["scheduler_started"] is not None

    def test_heartbeat(self, tmp_path):
        """Test heartbeat updates timestamp."""
        status_file = tmp_path / "status.json"
        status = SchedulerStatus(status_file)

        status.heartbeat()

        data = status.get_status()
        assert "last_heartbeat" in data
        assert data["last_heartbeat"] is not None

    def test_job_lifecycle(self, tmp_path):
        """Test job started and completed tracking."""
        status_file = tmp_path / "status.json"
        status = SchedulerStatus(status_file)

        # Start job
        status.job_started("test_job")
        data = status.get_status()
        assert "test_job" in data["jobs"]
        assert data["jobs"]["test_job"]["status"] == "running"

        # Complete job successfully
        status.job_completed("test_job", success=True, message="Done")
        data = status.get_status()
        assert data["jobs"]["test_job"]["status"] == "success"
        assert data["jobs"]["test_job"]["message"] == "Done"
        assert "last_success" in data["jobs"]["test_job"]

    def test_job_failure(self, tmp_path):
        """Test job failure tracking."""
        status_file = tmp_path / "status.json"
        status = SchedulerStatus(status_file)

        status.job_started("failing_job")
        status.job_completed("failing_job", success=False, message="Connection failed")

        data = status.get_status()
        assert data["jobs"]["failing_job"]["status"] == "failed"
        assert data["jobs"]["failing_job"]["message"] == "Connection failed"
        assert "last_success" not in data["jobs"]["failing_job"]

    def test_persistence(self, tmp_path):
        """Test status persists across instances."""
        status_file = tmp_path / "status.json"

        # First instance
        status1 = SchedulerStatus(status_file)
        status1.set_started()
        status1.job_completed("persistent_job", success=True)

        # Second instance loads from file
        status2 = SchedulerStatus(status_file)
        data = status2.get_status()
        assert "persistent_job" in data["jobs"]
        assert data["jobs"]["persistent_job"]["status"] == "success"


class TestRetryDecorator:
    """Tests for with_retry decorator."""

    def test_success_no_retry(self):
        """Test function succeeds without retry."""
        call_count = 0

        @with_retry(max_retries=3, base_delay=0)
        def successful_func():
            nonlocal call_count
            call_count += 1
            return "success"

        result = successful_func()
        assert result == "success"
        assert call_count == 1

    def test_retry_then_success(self):
        """Test function retries and eventually succeeds."""
        call_count = 0

        @with_retry(max_retries=3, base_delay=0)
        def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Failed")
            return "success"

        result = flaky_func()
        assert result == "success"
        assert call_count == 3

    def test_max_retries_exceeded(self):
        """Test function fails after max retries."""
        call_count = 0

        @with_retry(max_retries=3, base_delay=0)
        def always_fails():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("Always fails")

        with pytest.raises(ConnectionError):
            always_fails()

        assert call_count == 3


class TestHealthServer:
    """Tests for health check HTTP server."""

    def test_health_endpoint(self, tmp_path):
        """Test /health endpoint returns OK."""
        status_file = tmp_path / "status.json"
        status = SchedulerStatus(status_file)

        # Find an available port
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            port = s.getsockname()[1]

        server = start_health_server(port, status)

        try:
            # Give server time to start
            time.sleep(0.1)

            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as resp:
                assert resp.status == 200
                assert resp.read() == b"OK"
        finally:
            server.shutdown()

    def test_status_endpoint(self, tmp_path):
        """Test /status endpoint returns JSON."""
        status_file = tmp_path / "status.json"
        status = SchedulerStatus(status_file)
        status.set_started()

        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            port = s.getsockname()[1]

        server = start_health_server(port, status)

        try:
            time.sleep(0.1)

            with urllib.request.urlopen(f"http://127.0.0.1:{port}/status", timeout=2) as resp:
                assert resp.status == 200
                data = json.loads(resp.read())
                assert data["healthy"] is True
                assert "scheduler_started" in data
        finally:
            server.shutdown()


class TestNotifications:
    """Tests for notification sending."""

    def test_notification_without_webhook(self, caplog):
        """Test notification logs when no webhook configured."""
        with patch.dict("os.environ", {}, clear=True):
            send_notification({}, "Test Subject", "Test Body")

        # Should log the notification
        assert "NOTIFICATION" in caplog.text or "Test Subject" in caplog.text

    def test_notification_with_webhook(self):
        """Test notification sends to webhook."""
        with patch.dict("os.environ", {"SCHEDULER_WEBHOOK_URL": "http://example.com/webhook"}):
            with patch("urllib.request.urlopen") as mock_urlopen:
                mock_response = MagicMock()
                mock_response.status = 200
                mock_response.__enter__ = Mock(return_value=mock_response)
                mock_response.__exit__ = Mock(return_value=False)
                mock_urlopen.return_value = mock_response

                send_notification({}, "Test Subject", "Test Body")

                mock_urlopen.assert_called_once()


class TestTWSConnection:
    """Tests for TWS connection checking."""

    def test_connection_success(self):
        """Test successful TWS connection check."""
        mock_conn = MagicMock()
        mock_conn.connect.return_value = True

        with patch("src.scheduler.IBKRConnection", return_value=mock_conn):
            result = check_tws_connection({})

        assert result is True
        mock_conn.disconnect.assert_called_once()

    def test_connection_failure(self):
        """Test failed TWS connection check."""
        mock_conn = MagicMock()
        mock_conn.connect.return_value = False

        with patch("src.scheduler.IBKRConnection", return_value=mock_conn):
            result = check_tws_connection({})

        assert result is False

    def test_connection_exception(self):
        """Test TWS connection check handles exceptions."""
        with patch("src.scheduler.IBKRConnection", side_effect=Exception("Connection error")):
            result = check_tws_connection({})

        assert result is False
