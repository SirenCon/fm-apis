from django.core.management.base import BaseCommand, CommandError

from registration.emails import send_registration_email
from registration.models import Order


class Command(BaseCommand):
    help = "Resend a registration email given an order reference."

    def add_arguments(self, parser):
        parser.add_argument(
            "order_ref",
            type=str,
            help="The order reference to resend the registration email to.",
        )

    def handle(self, *args, **options):
        order_ref = options["order_ref"]

        try:
            order = Order.objects.get(reference=order_ref)
        except Order.DoesNotExist:
            raise CommandError("Order not found.")

        send_registration_email(order, order.billingEmail)

        print(f"Sent email to {order}")
