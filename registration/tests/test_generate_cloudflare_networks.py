from pathlib import Path
from unittest.mock import patch

import responses
from django.core.management import call_command
from django.test import TestCase


_path_cls = Path(".").__class__
path_patch = f"{_path_cls.__module__}.{_path_cls.__name__}.write_text"


def _get_ipv4_networks(request):
    status_code = 200
    headers = {"Content-Type": "text/plain;charset=UTF-8"}
    return (status_code, headers, "173.245.48.0/20")


def _get_ipv6_networks(request):
    status_code = 200
    headers = {"Content-Type": "text/plain;charset=UTF-8"}
    return (status_code, headers, "2400:cb00::/32")


class TestCloudflareMiddleware(TestCase):
    @responses.activate
    @patch(path_patch)
    def test_generates_to_file(self, patched):
        responses.add_callback(
            responses.GET,
            "https://www.cloudflare.com/ips-v4/",
            callback=_get_ipv4_networks,
        )

        responses.add_callback(
            responses.GET,
            "https://www.cloudflare.com/ips-v6/",
            callback=_get_ipv6_networks,
        )

        call_command("generate_cloudflare_networks")

        self.assertEqual(len(patched.mock_calls), 1)

        call_args = patched.mock_calls[0].args
        self.assertEqual(len(call_args), 1)

        file_content = call_args[0]

        expected_file_content = """
import ipaddress


IPV4_NETWORKS = [
    ipaddress.ip_network("173.245.48.0/20"),
]
IPV6_NETWORKS = [
    ipaddress.ip_network("2400:cb00::/32"),
]
""".lstrip()

        self.assertEqual(file_content, expected_file_content)
