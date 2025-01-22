from pathlib import Path

import requests
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Re-generates registration.middleware.networks from Cloudflare."

    def handle(self, *args, **options):
        ipv4_url = "https://www.cloudflare.com/ips-v4/"
        ipv6_url = "https://www.cloudflare.com/ips-v6/"

        ipv4_networks = requests.get(ipv4_url).text.splitlines()
        ipv6_networks = requests.get(ipv6_url).text.splitlines()

        networks_py = "import ipaddress\n\n\n"

        networks_py += "IPV4_NETWORKS = [\n"
        for ipv4_network in ipv4_networks:
            networks_py += f'    ipaddress.ip_network("{ipv4_network}"),\n'
        networks_py += "]\n"

        networks_py += "IPV6_NETWORKS = [\n"
        for ipv6_network in ipv6_networks:
            networks_py += f'    ipaddress.ip_network("{ipv6_network}"),\n'
        networks_py += "]\n"

        registration = Path(__file__).parent.parent.parent
        networks_file = registration / "middleware/networks.py"

        networks_file.write_text(networks_py)
