import logging
from datetime import datetime, timezone

from django.contrib.auth.models import AnonymousUser

log = logging.getLogger("registration")


class FilebeatMiddleware:
    """
    Sends request metrics to a Filebeat server.
    """
    def __init__(self, get_response):
        self.get_response = get_response
        self._request_started_at = None

    def __call__(self, request):
        self._request_started_at = datetime.now(timezone.utc)

        self.process_request(request)

        response = self.get_response(request)

        self.process_response(request, response)

        return response

    def _make_log_args(self, request):
        # Get the client IP
        cf_connecting_ip = request.headers.get("cf-connecting-ip")
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")

        if cf_connecting_ip:
            forwarded_for = cf_connecting_ip
        elif x_forwarded_for:
            forwarded_for = x_forwarded_for.split(",")[0]
        else:
            forwarded_for = ""

        client_ip = forwarded_for or request.META["REMOTE_ADDR"]

        # Get user agent
        user_agent = request.headers.get("user-agent")

        # Get SSL info
        is_ssl = request.is_secure()

        if is_ssl:
            tls_version = request.environ["werkzeug.socket"].version()
        else:
            tls_version = None

        # Get user info
        if request.user and not isinstance(request.user, AnonymousUser):
            user_id = request.user.id
            user_email = request.user.email
        else:
            user_id = None
            user_email = None

        return {
            "request.server_host": request.META["HTTP_HOST"],
            "request.method": request.method,
            "request.url": request.path,
            "request.client_ip": client_ip,
            "request.user_agent": user_agent,
            "request.request_size": request.headers.get("Content-Length"),
            "request.is_ssl": is_ssl,
            "request.tls_version": tls_version,
            "request.user_id": user_id,
            "request.user_email": user_email,
            "request.session_id": request.session.session_key,
        }

    def process_request(self, request):
        log_args = {
            "event.type": "request_started",
            "request.start_time": self._request_started_at.isoformat(),
        }

        request_log_args = self._make_log_args(request)
        log_args.update(request_log_args)

        log.info("Processing request", extra=log_args)

    def process_response(self, request, response):
        request_ended_at = datetime.now(timezone.utc)

        duration_ms = (request_ended_at - self._request_started_at).microseconds / 1000

        log_args = {
            "event.type": "request_finished",
            "request.start_time": self._request_started_at.isoformat(),
            "request.end_time": request_ended_at.isoformat(),
            "request.duration_ms": duration_ms,
            "request.status_code": response.status_code,
            "request.response_size": len(response.content),
        }

        request_log_args = self._make_log_args(request)
        log_args.update(request_log_args)

        log.info("Processed request", extra=log_args)

        return response

    def process_exception(self, request, exception):
        request_ended_at = datetime.now(timezone.utc)

        duration_ms = (request_ended_at - self._request_started_at).microseconds / 1000

        log_args = {
            "event.type": "request_crashed",
            "request.start_time": self._request_started_at.isoformat(),
            "request.end_time": request_ended_at.isoformat(),
            "request.duration_ms": duration_ms,
        }

        request_log_args = self._make_log_args(request)
        log_args.update(request_log_args)

        log.info("Processed request exception", extra=log_args)

        return None
