import base64
import hmac
import hashlib
import json
import logging

import requests
import sentry_sdk


class FilebeatHandler(logging.Handler):
    def __init__(self, *args, **kwargs):
        self._endpoint_url = kwargs.pop("endpoint_url")
        self._username = kwargs.pop("username")
        self._password = kwargs.pop("password")
        self._hmac_header = kwargs.pop("hmac_header")
        self._hmac_secret = kwargs.pop("hmac_secret")

        super().__init__(*args, **kwargs)

    @property
    def _auth_basic(self):
        user_pass = f"{self._username}:{self._password}".encode("utf-8")
        encoded = base64.b64encode(user_pass).decode("utf-8")
        return encoded

    def emit(self, record):
        data_to_send = json.dumps(dict(record.__dict__.items())).encode("utf-8")
        signature = hmac.new(
            self._hmac_secret.encode("utf-8"),
            msg=data_to_send,
            digestmod=hashlib.sha256,
        ).hexdigest()

        headers = {
            "Authorization": f"Basic {self._auth_basic}",
            "Content-Type": "application/json",
            self._hmac_header: f"sha256={signature}",
        }

        try:
            response = requests.post(self._endpoint_url, headers=headers, data=data_to_send, timeout=2)
            response.raise_for_status()
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
