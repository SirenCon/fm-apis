from unittest.mock import MagicMock

from django.test import TestCase

from registration.middleware.cloudflare import CloudflareMiddleware
from registration.middleware.networks import IPV4_NETWORKS


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
        remote_addr = str(IPV4_NETWORKS[0].broadcast_address - 1)

        request = MagicMock()
        request.META = {
            "HTTP_CF_CONNECTING_IP": "10.0.0.24",
            "REMOTE_ADDR": remote_addr,
        }
        request.path = "/registration/"
        request.sessionn = {}

        middleware = CloudflareMiddleware(request)
        response = middleware(request)

        self.assertEqual(request.return_value, response)
        self.assertEqual(request.META["REMOTE_ADDR"], "10.0.0.24")
