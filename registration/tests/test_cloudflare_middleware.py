from unittest.mock import MagicMock

from django.test import TestCase

from registration.middleware.cloudflare import CloudflareMiddleware
from registration.middleware.networks import IPV4_NETWORKS, IPV6_NETWORKS


class TestCloudflareMiddleware(TestCase):
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


    def test_middleware_fixes_remote_addr_ipv4(self):
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

    def test_middleware_fixes_remote_addr_ipv6(self):
        remote_addr = str(IPV6_NETWORKS[0].broadcast_address - 1)

        request = MagicMock()
        request.META = {
            "HTTP_CF_CONNECTING_IP": "fe80::f000:0000:0000:0000",
            "REMOTE_ADDR": remote_addr,
        }
        request.path = "/registration/"
        request.sessionn = {}

        middleware = CloudflareMiddleware(request)
        response = middleware(request)

        self.assertEqual(request.return_value, response)
        self.assertEqual(request.META["REMOTE_ADDR"], "fe80::f000:0000:0000:0000")
