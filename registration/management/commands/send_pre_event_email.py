from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.template.loader import render_to_string

import registration.views.common
from registration.emails import send_email
from registration.models import Event, Order, OrderItem


class Command(BaseCommand):
    help = "Send the pre-event notice email to all paid attendees for the 2026 event."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print recipients and EC status without actually sending any email.",
        )
        parser.add_argument(
            "--order-ref",
            type=str,
            default=None,
            help="Restrict sending to a single order reference (useful for testing).",
        )
        parser.add_argument(
            "--event-name",
            type=str,
            default=None,
            help="Name of the event to target (default: the event marked as default).",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        order_ref = options["order_ref"]
        event_name = options["event_name"]

        # -- Resolve event -------------------------------------------------------
        try:
            if event_name:
                event = Event.objects.get(name=event_name)
            else:
                event = Event.objects.get(default=True)
        except Event.DoesNotExist:
            raise CommandError(
                "No event found. Use --event-name to specify one, or mark an event as default."
            )

        self.stdout.write(f"Targeting event: {event.name}")

        registration_email = registration.views.common.get_registration_email(event)

        # -- Resolve orders -------------------------------------------------------
        if order_ref:
            orders = Order.objects.filter(reference=order_ref).select_related(
                "emergency_contact"
            )
            if not orders.exists():
                raise CommandError(f"No order found with reference '{order_ref}'.")
        else:
            # All paid/completed orders for the event (mirrors cron_metrics pattern)
            order_ids = (
                OrderItem.objects.filter(badge__event=event)
                .exclude(
                    Q(order__isnull=True)
                    | Q(order__billingType=Order.UNPAID)
                    | Q(
                        order__status__in=(
                            Order.FAILED,
                            Order.REFUNDED,
                            Order.REFUND_PENDING,
                        )
                    )
                    | Q(priceLevel__isnull=True)
                )
                .values_list("order_id", flat=True)
                .distinct()
            )
            orders = Order.objects.filter(id__in=order_ids).select_related(
                "emergency_contact"
            )

        total = orders.count()
        self.stdout.write(f"Found {total} order(s) to process.")

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN — no emails will be sent.\n")
            )

        sent = 0
        missing_ec = 0

        for order in orders:
            # -- Check emergency contact -----------------------------------------
            try:
                ec = order.emergency_contact
                has_ec = bool(ec.name and ec.phone)
            except Exception:
                has_ec = False

            if not has_ec:
                missing_ec += 1

            status_label = "EC: OK" if has_ec else "EC: MISSING"
            self.stdout.write(
                f"  [{status_label}] {order.reference} → {order.billingEmail}"
            )

            if dry_run:
                continue

            # -- Build and send email --------------------------------------------
            context = {
                "event": event,
                "billing_name": order.billingName or "Attendee",
                "reference": order.reference,
                "has_ec": has_ec,
            }

            msg_txt = render_to_string(
                "registration/emails/pre-event-notice.txt", context
            )
            msg_html = render_to_string(
                "registration/emails/pre-event-notice.html", context
            )

            send_email(
                registration_email,
                [order.billingEmail],
                f"SirenCon 2026 — See You Soon!",
                msg_txt,
                msg_html,
            )
            sent += 1

        # -- Summary -------------------------------------------------------------
        self.stdout.write("")
        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Dry run complete. Would send to {total} order(s); "
                    f"{missing_ec} missing emergency contact."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Done. Sent {sent}/{total} email(s); "
                    f"{missing_ec} order(s) had no emergency contact set."
                )
            )
