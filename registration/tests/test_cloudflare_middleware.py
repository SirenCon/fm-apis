from unittest.mock import MagicMock

from django.test import TestCase

from registration.middleware.cloudflare import CloudflareMiddleware


class TestCloudalreMiddleware(TestCase):
    def test_middleware_skips_local_network(self):
        request = MagicMock()
        request.META = {
            "HTTP_CF_CONNECTING_IP": "10.0.0.24",
            "REMOTE_ADDR": "127.0.0.1",
        }
        request.path = "/registration/"
        request.sessionn = {}

        middleware = CloudflareMiddleware(request)
        response = middleware(request)

        self.assertEqual(request.return_value, response)
        self.assertEqual(request.META["REMOTE_ADDR"], "127.0.0.1")


    def test_middleware_fixes_remote_addr(self):
        request = MagicMock()
        request.META = {
            "HTTP_CF_CONNECTING_IP": "10.0.0.24",
            "REMOTE_ADDR": "173.245.49.1",
        }
        request.path = "/registration/"
        request.sessionn = {}

        middleware = CloudflareMiddleware(request)
        response = middleware(request)

        self.assertEqual(request.return_value, response)
        self.assertEqual(request.META["REMOTE_ADDR"], "10.0.0.24")
