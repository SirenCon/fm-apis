from unittest.mock import MagicMock
import base64
import hmac
import hashlib
import json
import logging

from django.test import TestCase
import responses

from registration.middleware.logging import LoggingMiddleware
from registration.utils.filebeat_logging_handler import FilebeatHandler


class _FakeSession:
    def __init__(self):
        self.session_key = "12345"


class _FakeUser:
    def __init__(self):
        self.id = 1
        self.email = "test@example.net"


class _FakeResponse:
    def __init__(self):
        self.status_code = 200
        self.content = ""


log = logging.getLogger("registration")


def _handle_filebeat_entry(request):
    headers = {"Content-Type": "application/json"}
    return (200, headers, "{}")


class TestLoggingMiddleware(TestCase):
    def setUp(self):
        self._old_handlers = list(log.handlers)

        log.handlers.clear()

        handler = FilebeatHandler(
            endpoint_url="http://127.0.0.1/local/",
            username="username",
            password="password",
            hmac_header="x-256-secret",
            hmac_secret="hmac_secret",
        )
        log.addHandler(handler)

    def tearDown(self):
        log.handlers = self._old_handlers

    @responses.activate
    def test_middleware_logs_info(self):
        responses.add_callback(
            responses.POST,
            "http://127.0.0.1/local/",
            callback=_handle_filebeat_entry,
            content_type="application/json",
        )

        request = MagicMock()
        request.META = {
            "HTTP_CF_CONNECTING_IP": "10.0.0.24",
            "HTTP_HOST": "127.0.0.1",
            "REMOTE_ADDR": "127.0.0.1",
        }
        request.path = "/registration/"
        request.method = "GET"
        request.headers = {
            "cf-connecting-ip": "10.0.0.24",
            "Content-Length": 0,
            "user-agent": "test client",
        }
        request.session = _FakeSession()
        request.is_secure = lambda: False
        request.user = _FakeUser()
        request.return_value = _FakeResponse()

        middleware = LoggingMiddleware(request)
        response = middleware(request)

        self.assertEqual(request.return_value, response)
        self.assertEqual(request.META["REMOTE_ADDR"], "127.0.0.1")

        calls = list(responses.calls)
        self.assertEqual(len(calls), 2)

        call = calls[0].request
        self.assertEqual(call.method, "POST")
        self.assertEqual(call.params, {})
        self.assertEqual(call.url, "http://127.0.0.1/local/")
        self.assertEqual(call.headers["Content-Type"], "application/json")

        expected = base64.b64encode(b"username:password").decode("utf-8")
        auth = call.headers["Authorization"]
        self.assertEqual(auth.startswith("Basic "), True)
        auth = auth.removeprefix("Basic ")
        self.assertEqual(auth, expected)

        data = bytes(call.body)

        signature = hmac.new(
            b"hmac_secret",
            msg=data,
            digestmod=hashlib.sha256,
        ).hexdigest()

        sig_header = call.headers["x-256-secret"]
        self.assertEqual(sig_header.startswith("sha256="), True)
        sig_header = sig_header.removeprefix("sha256=")
        self.assertEqual(sig_header, signature)

        self.assertEqual(call.headers["Content-Length"], str(len(data)))

        log_args = json.loads(data)
        self.assertEqual(log_args["name"], "registration")
        self.assertEqual(log_args["msg"], "Processing request")
        self.assertEqual(log_args["levelname"], "INFO")
        self.assertEqual(log_args["levelno"], 20)
        self.assertEqual(log_args["event.type"], "request_started")
        self.assertEqual(log_args["request.server_host"], "127.0.0.1")
        self.assertEqual(log_args["request.method"], "GET")
        self.assertEqual(log_args["request.url"], "/registration/")
        self.assertEqual(log_args["request.client_ip"], "10.0.0.24")
        self.assertEqual(log_args["request.user_agent"], "test client")
        self.assertEqual(log_args["request.request_size"], 0)
        self.assertEqual(log_args["request.is_ssl"], False)
        self.assertEqual(log_args["request.tls_version"], None)
        self.assertEqual(log_args["request.user_id"], 1)
        self.assertEqual(log_args["request.user_email"], "test@example.net")
        self.assertEqual(log_args["request.session_id"], "12345")

        call = calls[1].request
        self.assertEqual(call.method, "POST")
        self.assertEqual(call.params, {})
        self.assertEqual(call.url, "http://127.0.0.1/local/")
        self.assertEqual(call.headers["Content-Type"], "application/json")

        expected = base64.b64encode(b"username:password").decode("utf-8")
        auth = call.headers["Authorization"]
        self.assertEqual(auth.startswith("Basic "), True)
        auth = auth.removeprefix("Basic ")
        self.assertEqual(auth, expected)

        data = bytes(call.body)

        signature = hmac.new(
            b"hmac_secret",
            msg=data,
            digestmod=hashlib.sha256,
        ).hexdigest()

        sig_header = call.headers["x-256-secret"]
        self.assertEqual(sig_header.startswith("sha256="), True)
        sig_header = sig_header.removeprefix("sha256=")
        self.assertEqual(sig_header, signature)

        self.assertEqual(call.headers["Content-Length"], str(len(data)))

        log_args = json.loads(data)
        self.assertEqual(log_args["name"], "registration")
        self.assertEqual(log_args["msg"], "Processed request")
        self.assertEqual(log_args["levelname"], "INFO")
        self.assertEqual(log_args["levelno"], 20)
        self.assertEqual(log_args["event.type"], "request_finished")
        self.assertEqual(log_args["request.server_host"], "127.0.0.1")
        self.assertEqual(log_args["request.method"], "GET")
        self.assertEqual(log_args["request.url"], "/registration/")
        self.assertEqual(log_args["request.client_ip"], "10.0.0.24")
        self.assertEqual(log_args["request.user_agent"], "test client")
        self.assertEqual(log_args["request.request_size"], 0)
        self.assertEqual(log_args["request.is_ssl"], False)
        self.assertEqual(log_args["request.tls_version"], None)
        self.assertEqual(log_args["request.user_id"], 1)
        self.assertEqual(log_args["request.user_email"], "test@example.net")
        self.assertEqual(log_args["request.session_id"], "12345")
        self.assertEqual(log_args["request.status_code"], 200)
