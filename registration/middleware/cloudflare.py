import ipaddress

from .networks import (
    IPV4_NETWORKS,
    IPV6_NETWORKS,
)


def _is_cf_ip(remote_ip) -> bool:
    networks = []

    if remote_ip.version == 4:
        networks = IPV4_NETWORKS
    elif remote_ip.version == 6:
        networks = IPV6_NETWORKS

    for network in networks:
        if remote_ip in network:
            return True

    return False


class CloudflareMiddleware:
    """
    Replaces REMOTE_ADDR with the IP from Cloudflare's headers.
    """
    def __init__(self, get_response):
        self.get_response = get_response
        self._cloudflare_ip_header = "HTTP_CF_CONNECTING_IP"

    def _patch_cf_ip(self, request):
        if self._cloudflare_ip_header not in request.META:
            return

        remote_ip = ipaddress.ip_address(request.META["REMOTE_ADDR"])
        if not _is_cf_ip(remote_ip):
            return

        request.META["REMOTE_ADDR"] = request.META[self._cloudflare_ip_header]

    def __call__(self, request):
        self._patch_cf_ip(request)
        response = self.get_response(request)
        return response
