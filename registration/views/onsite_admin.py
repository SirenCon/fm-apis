import base64
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import List, Optional, Union

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import permission_required
from django.contrib.messages import get_messages
from django.contrib.postgres.search import TrigramSimilarity
from django.core.signing import TimestampSigner
from django.db.models import F, Func, Q, Sum, Value
from django.http import HttpRequest, HttpResponseRedirect, JsonResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.views.decorators.csrf import csrf_exempt

from registration import admin, mqtt, payments
from registration.models import (
    Badge,
    Cashdrawer,
    Discount,
    Event,
    Firebase,
    Order,
    OrderItem,
    ShirtSizes,
    Staff,
    get_token,
)
from registration.views.attendee import get_attendee_age
from registration.views.common import logger
from registration.views.ordering import (
    get_discount_total,
    get_order_item_option_total,
)


def flatten(l):
    return [item for sublist in l for item in sublist]


logger = logging.getLogger(__name__)

TWOPLACES = Decimal(10) ** -2


def get_active_terminal(request):
    term_id = request.session.get("terminal")
    if term_id:
        try:
            return Firebase.objects.get(pk=int(term_id))
        except Firebase.DoesNotExist:
            return None
    return None


@staff_member_required
def onsite_admin(request):
    # Modify a dummy session variable to keep it alive
    request.session["heartbeat"] = time.time()

    terminals = list(Firebase.objects.order_by("name").all())
    term = request.session.get("terminal", None)

    errors = []

    # Set default payment terminal to use:
    if term is None and len(terminals) > 0:
        request.session["terminal"] = terminals[0].id

    if len(terminals) == 0:
        errors.append(
            {
                "type": "danger",
                "code": "ERROR_NO_TERMINAL",
                "text": "It looks like no payment terminals have been configured "
                "for this server yet. Check that the APIS Terminal app is "
                "running, and has been configured for the correct URL and API key.",
            }
        )

    # No terminal selection saved in session - see if one's
    # on the URL (that way it'll survive session timeouts)
    url_terminal = request.GET.get("terminal", None)
    logger.info("Terminal from GET parameter: {0}".format(url_terminal))
    if url_terminal is not None:
        try:
            terminal_obj = Firebase.objects.get(id=int(url_terminal))
            request.session["terminal"] = terminal_obj.id
        except Firebase.DoesNotExist:
            del request.session["terminal"]
            errors.append(
                {
                    "type": "warning",
                    "text": "The payment terminal specified has not registered with the server",
                }
            )
        except ValueError:
            # weren't passed an integer
            errors.append({"type": "danger", "text": "Invalid terminal specified"})

    terminal = get_active_terminal(request)
    mqtt_auth = None
    if terminal:
        mqtt_auth = mqtt.get_onsite_admin_token(terminal)

    selected_terminal = None
    if terminal:
        selected_terminal = {
            "id": terminal.id,
            "features": {
                "print_via_mqtt": terminal.print_via_mqtt is not None,
                "square_terminal": terminal.square_terminal_id is not None,
                "payment_type": terminal.payment_type,
                "cashdrawer": terminal.cashdrawer,
            }
        }

    context = {
        "settings": json.dumps({
            "user": {
                "id": request.user.id,
                "email": request.user.email,
                "station": terminal.name if terminal else None,
            },
            "sentry": {
                "enabled": getattr(settings, "SENTRY_ENABLED", False),
                "user_reports": getattr(settings, "SENTRY_USER_REPORTS", False),
                "frontend_dsn": getattr(settings, "SENTRY_FRONTEND_DSN", None),
                "environment": getattr(settings, "SENTRY_ENVIRONMENT", None),
                "release": getattr(settings, "SENTRY_RELEASE", None),
            },
            "errors": errors,
            "mqtt": {
                "broker": getattr(settings, "MQTT_EXTERNAL_BROKER", None),
                "auth": mqtt_auth,
            },
            "shirt_sizes": [{"name": s.name, "id": s.id} for s in ShirtSizes.objects.all()],
            "urls": {
                "assign_badge_number": reverse("registration:assign_badge_number"),
                "mark_checked_in": reverse("registration:mark_checked_in"),
                "cash_deposit": reverse("registration:cash_deposit"),
                "cash_pickup": reverse("registration:cash_pickup"),
                "close_drawer": reverse("registration:close_drawer"),
                "complete_cash_transaction": reverse("registration:complete_cash_transaction"),
                "enable_payment": reverse("registration:enable_payment"),
                "logout": reverse("registration:logout"),
                "no_sale": reverse("registration:no_sale"),
                "onsite_add_to_cart": reverse("registration:onsite_add_to_cart"),
                "onsite_admin_cart": reverse("registration:onsite_admin_cart"),
                "onsite_admin_clear_cart": reverse("registration:onsite_admin_clear_cart"),
                "onsite_admin_search": reverse("registration:onsite_admin_search"),
                "onsite_admin_transfer_cart": reverse("registration:onsite_admin_transfer_cart"),
                "onsite_admin": reverse("registration:onsite_admin"),
                "onsite_create_discount": reverse("registration:onsite_create_discount"),
                "onsite_print_badges": reverse("registration:onsite_print_badges"),
                "onsite_print_clear": reverse("registration:onsite_print_clear"),
                "onsite_print_receipts": reverse("registration:onsite_print_receipts"),
                "onsite_remove_from_cart": reverse("registration:onsite_remove_from_cart"),
                "onsite": reverse("registration:onsite"),
                "open_drawer": reverse("registration:open_drawer"),
                "pdf": reverse("registration:pdf"),
                "registration_badge_change": reverse("admin:registration_badge_change", args=(0,)),
                "safe_drop": reverse("registration:safe_drop"),
                "set_terminal_status": reverse("registration:terminal_status"),
            },
            "permissions": {
                "cash": request.user.has_perm("registration.cash"),
                "cash_admin": request.user.has_perm("registration.cash_admin"),
                "discount": request.user.has_perm("registration.discount"),
            },
            "terminals": {
                "selected": selected_terminal,
                "available": [{"id": terminal.id, "name": terminal.name} for terminal in terminals],
            },
        }),
    }

    return render(request, "registration/onsite-admin.html", context)


@dataclass
class SearchFields:
    query: str
    birthday: Optional[str] = None
    badge_ids: Optional[List[int]] = None

    @classmethod
    def parse(cls, query: str) -> "SearchFields":
        badge_nums = re.search(r"num:([0-9,]+)", query)
        if badge_nums:
            try:
                badge_ids = [int(num) for num in badge_nums.group(1).split(",")]
                return SearchFields(badge_ids=badge_ids, query="")
            except ValueError:
                query = query.replace(badge_nums.group(0), "")
                pass

        birthday = re.search(r"birthday:([0-9-]{10}) ?", query)
        if birthday:
            query = query.replace(birthday.group(0), "")
            birthday = birthday.group(1)

        query = query.strip()

        return SearchFields(query=query, birthday=birthday)


@staff_member_required
def onsite_admin_search_orders(request):
    event = Event.objects.get(default=True)
    query = request.GET.get("search", None)
    if query is None:
        return redirect("registration:onsite_admin")

    data = []

    query = query.strip()

    def make_response_object(order_item):
        return {
            "id": order_item.order_id,
            "reference": order_item.order.reference,
            "editUrl": reverse("admin:registration_order_change", args=(order_item.order_id,)),
            "attendee": {
                "firstName": order_item.badge.attendee.firstName,
                "lastName": order_item.badge.attendee.lastName,
                "preferredName": order_item.badge.attendee.preferredName,
            },
        }

    checked_order_ids = set()
    filtered_orders = {}

    order_item_results = OrderItem.objects.all()
    for order_item in order_item_results:
        if not order_item.badge:
            continue

        if order_item.order_id in checked_order_ids:
            continue

        checked_order_ids.add(order_item.order_id)

        if query.lower() in order_item.order.reference:
            filtered_orders[order_item.order_id] = make_response_object(order_item)
            continue

        full_name = order_item.badge.attendee.firstName + " " + order_item.badge.attendee.lastName
        if query.lower() in full_name.lower():
            filtered_orders[order_item.order_id] = make_response_object(order_item)
            continue

    data = list(filtered_orders.values())

    from django.db import connection
    print(len(connection.queries))

    return JsonResponse({"success": True, "results": data})


@staff_member_required
def onsite_admin_search(request):
    event = Event.objects.get(default=True)
    query = request.GET.get("search", None)
    if query is None:
        return redirect("registration:onsite_admin")

    data = []

    def collectBadges(badges):
        for badge in badges:
            order = OrderItem.objects.filter(badge=badge).first().order
            data.append({
                "id": badge.id,
                "editUrl": reverse("admin:registration_badge_change", args=(badge.id,)),
                "orderReference": order.reference,
                "checkedInDate": order.checkedInDate,
                "wristBandCountPickedUp": order.wristBandCountPickedUp,
                "cabinAssignment": order.cabinAssignment,
                "campsiteAssignment": order.campsiteAssignment,
                "attendee": {
                    "firstName": badge.attendee.firstName,
                    "lastName": badge.attendee.lastName,
                    "preferredName": badge.attendee.preferredName,
                },
                "badgeName": badge.badgeName,
                "badgeNumber": badge.badgeNumber,
                "abandoned": badge.abandoned,
            })

    query = query.strip()

    fields = SearchFields.parse(query)

    if fields.badge_ids:
        badges = Badge.objects.filter(event=event, badgeNumber__in=fields.badge_ids)
        collectBadges(badges)

    fullName = Func(F("attendee__firstName"), Value(" "), F("attendee__lastName"), function="CONCAT")
    greaterSimilarity = Func("name_similarity", "badge_similarity", function="GREATEST")

    filters = (Q(name_similarity__gte=0.4) | Q(badge_similarity__gte=0.6) | Q(attendee__lastName__iexact=fields.query))

    if fields.birthday:
        filters = filters & Q(attendee__birthdate=fields.birthday)

    results = Badge.objects.annotate(
        name_similarity=TrigramSimilarity(fullName, fields.query),
        badge_similarity=TrigramSimilarity("badgeName", fields.query),
    ).filter(
        Q(event=event) & filters
    ).order_by(greaterSimilarity).reverse().prefetch_related("attendee")[:50]

    collectBadges(results)

    return JsonResponse({"success": True, "results": data})


def update_terminal_status(request, status: str) -> JsonResponse:
    active = get_terminal_from_request(request)
    if not active:
        return JsonResponse({"success": False, "reason": "No terminal associated with request"}, status=400)

    stateCommand = status
    if stateCommand == "close":
        stateCommand = "closed"
    mqtt.send_mqtt_message(f"{mqtt.get_topic('admin', active.name)}/terminal/state", stateCommand)

    if status not in ("close", "open", "ready"):
        return JsonResponse({"success": True})

    return send_mqtt_message_to_terminal(active, {
        status: {},
    })


@staff_member_required
def set_terminal_status(request):
    status = request.GET.get("status", "close")
    return update_terminal_status(request, status)


def get_terminal_from_request(request) -> Optional[Firebase]:
    url_terminal = request.GET.get("terminal", None)
    session_terminal = request.session.get("terminal", None)

    active = None

    if url_terminal:
        try:
            active = Firebase.objects.get(id=int(url_terminal))
            request.session["terminal"] = active.id
        except (ValueError, Firebase.DoesNotExist):
            return None

    if not active and session_terminal:
        try:
            active = Firebase.objects.get(id=int(session_terminal))
        except Firebase.DoesNotExist:
            return None

    return active


def send_mqtt_message_to_terminal(request: Union[HttpRequest, Firebase], data: dict) -> JsonResponse:
    if isinstance(request, Firebase):
        active = request
    else:
        active = get_terminal_from_request(request)
        if not active:
            return JsonResponse({"sucess": False, "reason": "No terminal associated with request"}, status=400)

    name = active.name
    topic = f'{mqtt.get_topic("terminal", name)}/action'

    try:
        mqtt.send_mqtt_message(topic, data)
    except Exception as ex:
        logger.error("could not send mqtt message: %s", ex)
        return JsonResponse({"success": False, "reason": "Could not send MQTT message"}, status=500)

    return JsonResponse({"success": True})


@staff_member_required
def enable_payment(request):
    cart = request.session.get("cart", None)
    if cart is None:
        request.session["cart"] = []
        return JsonResponse(
            {"success": False, "message": "Cart not initialized"}, status=200
        )

    badges = []
    first_order = None

    for pk in cart:
        try:
            badge = Badge.objects.get(id=pk)
            badges.append(badge)

            order = badge.getOrder()
            if first_order is None:
                first_order = order
            else:
                # FIXME: use order.onsite_reference instead.
                # FIXME: Put this in cash handling, too
                # Reassign order references of items in cart to match first:
                order = badge.getOrder()
                order.reference = first_order.reference
                order.save()
        except Badge.DoesNotExist:
            cart.remove(pk)
            logger.error(
                "ID {0} was in cart but doesn't exist in the database".format(pk)
            )

    # Force a cart refresh to get the latest order reference to the terminal
    onsite_admin_cart(request)

    data = build_result(cart)

    terminal = get_terminal_from_request(request)
    if not terminal:
        return JsonResponse({"sucess": False, "reason": "No terminal associated with request."})

    order_id = payments.create_square_order(str(terminal.name), data)

    if (terminal.payment_type == Firebase.SQUARE_TERMINAL or request.GET.get("fallback", None) == "true") and terminal.square_terminal_id:
        resp = payments.prompt_terminal_payment(
            request,
            str(terminal.square_terminal_id),
            int(data["total"] * 100),
            data["reference"],
            render_to_string("registration/customer-note.txt", data),
            order_id
        )

        return JsonResponse({
            "success": resp.is_success(),
            "reason": ", ".join([error["detail"] for error in resp.errors]) if resp.errors else None,
        })
    elif terminal.payment_type == Firebase.MQTT_REGISTER_APP:
        return send_mqtt_message_to_terminal(terminal, {
            "processPayment": {
                "orderId": order_id,
                "total": int(data["total"] * 100),
                "reference": data["reference"],
                "note": render_to_string("registration/customer-note.txt", data),
            }
        })
    else:
        return JsonResponse({
            "success": False,
            "reason": "Terminal does not have payment type",
        })


@staff_member_required
def assign_badge_number(request):
    request_badges = json.loads(request.body)

    badge_payload = {badge["id"]: badge for badge in request_badges}

    badge_set = Badge.objects.filter(id__in=list(badge_payload.keys()))

    admin.assign_badge_numbers(None, request, badge_set)
    errors = get_messages_list(request)
    if errors:
        return JsonResponse(
            {"success": False, "errors": errors, "message": "\n".join(errors)},
            status=400,
        )
    return JsonResponse({"success": True})


@staff_member_required
def mark_checked_in(request):
    parsed_body = json.loads(request.body)
    print(parsed_body)

    order_reference = parsed_body["orderReference"]
    wristband_count = int(parsed_body["wristBandCount"])
    cabin_numer = parsed_body["cabinNumber"]
    campsite = parsed_body["campsite"]
    attending_dinner = parsed_body["attendingDinner"]

    order = Order.objects.filter(reference=order_reference).first()
    print(order)

    if not order:
        return JsonResponse({
            "success": False,
            "errors": ["Order not found"],
            "message": "Order not found",
        })

    order.checkedInDate = timezone.now()
    order.wristBandCountPickedUp = wristband_count
    order.cabinAssignment = cabin_numer
    order.campsiteAssignment = campsite
    order.attendingDinner = attending_dinner
    order.save()

    return JsonResponse({"success": True, "message": "Guest has been checked in"})


def get_messages_list(request):
    storage = get_messages(request)
    return [message.message for message in storage]


@staff_member_required
def onsite_print_badges(request):
    badge_list = request.GET.getlist("id")

    if getattr(settings, "PRINT_RENDERER", "wkhtmltopdf") == "gotenberg":
        terminal = get_active_terminal(request)

        signer = TimestampSigner()
        data = signer.sign_object({
            "badge_ids": [int(badge_id) for badge_id in badge_list],
            "terminal": terminal.name if terminal else None,
        })

        pdf_path = reverse("registration:pdf") + f"?data={data}"
    else:
        queryset = Badge.objects.filter(id__in=badge_list)
        pdf_name = admin.generate_badge_labels(queryset, request)

        pdf_path = reverse("registration:pdf") + f"?file={pdf_name}"

        # Async notify the frontend to refresh the cart
        logger.info("Refreshing admin cart")
        admin_push_cart_refresh(request)

    print_url = reverse("registration:print") + "?" + urlencode({"file": pdf_path})

    return JsonResponse(
        {
            "success": True,
            "next": request.get_full_path(),
            "file": pdf_path,
            "url": print_url,
        }
    )


def admin_push_cart_refresh(request):
    terminal = get_active_terminal(request)
    if terminal:
        topic = f"{mqtt.get_topic('admin', terminal.name)}/refresh"
        mqtt.send_mqtt_message(topic, None)


# TODO: update for square SDK data type (fetch txn from square API and store in order.apiData)
@csrf_exempt
def complete_square_transaction(request):
    try:
        token = request.headers.get("authorization").removeprefix("Bearer ")
    except:
        return JsonResponse({"success": False, "reason": "Invalid authorization"}, status=401)

    try:
        terminal = Firebase.objects.get(token=token)
        request.session["terminal"] = terminal.id
    except Firebase.DoesNotExist:
        return JsonResponse(
            {
                "success": False,
                "reason": "Unknown token",
            },
            status=401,
        )

    data = json.loads(request.body)

    reference = data.get("reference")
    paymentId = data.get("paymentId")

    if not reference or not paymentId:
        return JsonResponse(
            {
                "success": False,
                "reason": "reference and transactionId are required parameters",
            },
            status=400,
        )

    # Things we need:
    #   orderID or reference (passed to square by metadata)
    # Square returns:
    #   clientTransactionId (offline payments)
    #   serverTransactionId (online payments)

    try:
        orders = Order.objects.filter(reference=reference).prefetch_related()
    except Order.DoesNotExist:
        logger.error("No order matching reference {0}".format(reference))
        return JsonResponse(
            {
                "success": False,
                "reason": "No order matching the reference specified exists",
            },
            status=404,
        )

    combine_orders(orders)

    store_api_data = {}

    order = orders[0]
    order.billingType = Order.CREDIT

    # Lookup the payment(s?) associated with this order:
    if paymentId:
        store_api_data["payment"] = {"id": paymentId}
        order.status = Order.COMPLETED
        order.settledDate = timezone.now()
    else:
        order.status = Order.CAPTURED
        order.notes = "No paymentId."

    order.status = Order.COMPLETED
    order.settledDate = timezone.now()

    order.apiData = json.dumps(store_api_data)
    order.save()

    if paymentId:
        status, errors = payments.refresh_payment(order, store_api_data)
        if not status:
            return JsonResponse({"success": False, "error": errors}, status=210)

    admin_push_cart_refresh(request)

    return JsonResponse({"success": True})


def combine_orders(orders):
    # If there is more than one order, we should flatten them into one by reassigning all these
    # orderItems to the first order, and delete the rest.
    first_order = orders[0]

    if len(orders) > 1:
        order_items = []

        for order in orders[1:]:
            order_items += order.orderitem_set.all()
            first_order.notes += (
                f"\n[Combined from order reference {order.reference}]\n{order.notes}\n"
            )

        for order_item in order_items:
            old_order = order_item.order
            order_item.order = first_order
            if old_order and old_order.id:
                logger.warning("Deleting old order id={0}".format(old_order.id))
                old_order.delete()
            order_item.save()

        first_order.save()


@staff_member_required
@permission_required("order.cash_admin")
def drawer_status(request):
    if Cashdrawer.objects.count() == 0:
        return JsonResponse({"success": False})
    total = Cashdrawer.objects.all().aggregate(Sum("total"))
    drawer_total = Decimal(total["total__sum"])
    if drawer_total == 0:
        status = "CLOSED"
    elif drawer_total < 0:
        status = "SHORT"
    elif drawer_total > 0:
        status = "OPEN"
    return JsonResponse({"success": True, "total": drawer_total, "status": status})


@staff_member_required
@permission_required("order.cash_admin")
def no_sale(request):
    position = get_active_terminal(request)
    topic = f"{mqtt.get_topic('receipts', position.name)}/no_sale"
    mqtt.send_mqtt_message(topic)

    return JsonResponse({"success": True})


@staff_member_required
@permission_required("order.cash_admin")
def print_audit_receipt(request, audit_type, cash_ledger, cashdraw=True):
    position = get_active_terminal(request)
    event = Event.objects.get(default=True)
    payload = {
        "v": 1,
        "event": event.name,
        "terminal": position.name,
        "type": audit_type,
        "amount": abs(cash_ledger.total),
        "user": request.user.username,
        "timestamp": cash_ledger.timestamp.isoformat(),
        "cashdraw": cashdraw,
    }

    topic = f"{mqtt.get_topic('receipts', position.name)}/audit_slip"

    mqtt.send_mqtt_message(topic, payload)


def cash_audit_action(request, action):
    cashdraw = True
    amount = Decimal(request.POST.get("amount", None))
    position = get_active_terminal(request)
    if action in (Cashdrawer.DROP, Cashdrawer.PICKUP, Cashdrawer.CLOSE):
        amount = -abs(amount)
        cashdraw = False
    cash_ledger = Cashdrawer(
        action=action, total=amount, user=request.user, position=position
    )
    cash_ledger.save()
    cash_ledger.refresh_from_db()
    print_audit_receipt(request, action, cash_ledger, cashdraw)

    return JsonResponse({"success": True})


@staff_member_required
@permission_required("order.cash_admin")
def open_drawer(request):
    return cash_audit_action(request, Cashdrawer.OPEN)


@staff_member_required
@permission_required("order.cash_admin")
def cash_deposit(request):
    return cash_audit_action(request, Cashdrawer.DEPOSIT)


@staff_member_required
@permission_required("order.cash_admin")
def safe_drop(request):
    return cash_audit_action(request, Cashdrawer.DROP)


@staff_member_required
@permission_required("order.cash_admin")
def cash_pickup(request):
    return cash_audit_action(request, Cashdrawer.PICKUP)


@staff_member_required
@permission_required("order.cash_admin")
def close_drawer(request):
    return cash_audit_action(request, Cashdrawer.CLOSE)


def cash_receipt_payload(order: Order, tendered: str, total: str) -> dict:
    order_items = OrderItem.objects.filter(order=order)
    attendee_options = []
    for item in order_items:
        attendee_options.extend(get_line_items(item.attendeeoptions_set.all()))

    # discounts
    if order.discount:
        if order.discount.amountOff:
            attendee_options.append(
                {"item": "Discount", "price": "-${0}".format(order.discount.amountOff)}
            )
        elif order.discount.percentOff:
            attendee_options.append(
                {"item": "Discount", "price": "-%{0}".format(order.discount.percentOff)}
            )

    event = Event.objects.get(default=True)
    payload = {
        "v": 1,
        "event": event.name,
        "line_items": attendee_options,
        "donations": {"org": {"name": event.name, "price": str(order.orgDonation)}},
        "total": order.total,
        "payment": {
            "type": order.billingType,
            "tendered": Decimal(tendered),
            "change": Decimal(tendered) - Decimal(total),
            "details": "Ref: {0}".format(order.reference),
        },
        "reference": order.reference,
    }

    if event.charity:
        payload["donations"]["charity"] = (
            {"name": event.charity.name, "price": str(order.charityDonation)},
        )

    return payload


@staff_member_required
@permission_required("order.cash")
def complete_cash_transaction(request):
    reference = request.GET.get("reference", None)
    total = request.GET.get("total", None)
    tendered = request.GET.get("tendered", None)

    if reference is None or tendered is None or total is None:
        return JsonResponse(
            {
                "success": False,
                "reason": "Reference, tendered, and total are required parameters",
            },
            status=400,
        )

    try:
        orders = Order.objects.filter(reference=reference).prefetch_related()
    except Order.DoesNotExist:
        return JsonResponse(
            {
                "success": False,
                "reason": "No order matching the reference specified exists",
            },
            status=404,
        )

    combine_orders(orders)

    order = orders[0]
    order.billingType = Order.CASH
    order.status = Order.COMPLETED
    order.settledDate = timezone.now()
    order.notes = json.dumps({"type": "cash", "tendered": tendered})
    order.save()

    txn = Cashdrawer(
        action=Cashdrawer.TRANSACTION, total=total, tendered=tendered, user=request.user
    )
    txn.save()

    payload = cash_receipt_payload(order, tendered, total)

    term = request.session.get("terminal", None)
    active = Firebase.objects.get(id=term)
    topic = f"{mqtt.get_topic('receipts', active.name)}/print_cash"

    mqtt.send_mqtt_message(topic, payload)

    return JsonResponse({"success": True})


@csrf_exempt
def firebase_register(request):
    key = request.GET.get("key", "")
    if key != settings.REGISTER_KEY:
        return JsonResponse(
            {"success": False, "reason": "Incorrect API key"}, status=401
        )

    token = request.GET.get("token", None)
    name = request.GET.get("name", None)
    if token is None or name is None:
        return JsonResponse(
            {"success": False, "reason": "Must specify token and name parameter"},
            status=400,
        )

    # Upsert if a new token with an existing name tries to register
    try:
        old_terminal = Firebase.objects.get(name=name)
        old_terminal.token = token
        old_terminal.save()
        return JsonResponse({"success": True, "updated": True})
    except Firebase.DoesNotExist:
        pass
    except Exception as e:
        return JsonResponse(
            {
                "success": False,
                "reason": "Failed while attempting to update existing name entry",
            },
            status=500,
        )

    try:
        terminal = Firebase(token=token, name=name)
        terminal.save()
    except Exception as e:
        logger.exception(e)
        logger.error("Error while saving Firebase token to database")
        return JsonResponse(
            {"success": False, "reason": "Error while saving to database"}, status=500
        )

    return JsonResponse({"success": True, "updated": False})


@csrf_exempt
def firebase_lookup(request):
    # Returns the common name stored for a given firebase token
    # (So client can notify server if either changes)
    token = request.GET.get("token", None)
    if token is None:
        return JsonResponse(
            {"success": False, "reason": "Must specify token parameter"}, status=400
        )

    try:
        terminal = Firebase.objects.get(token=token)
        return JsonResponse(
            {"success": True, "name": terminal.name, "closed": terminal.closed}
        )
    except Firebase.DoesNotExist:
        return JsonResponse(
            {"success": False, "reason": "No such token registered"}, status=404
        )


def get_discount_dict(discount):
    if discount:
        reason = "\n\n---\n\n".join(filter(None, [discount.reason, discount.notes]))

        return {
            "name": discount.codeName,
            "percent_off": discount.percentOff,
            "amount_off": discount.amountOff,
            "id": discount.id,
            "valid": discount.isValid(),
            "status": discount.status,
            "reason": reason,
        }

    return None


def get_line_items(attendee_options):
    out = []
    for option in attendee_options:
        option_dict = {
            "item": option.option.optionName,
            "price": option.option.optionPrice,
            "quantity": 1,
            "total": option.option.optionPrice,
            "optionExtraType": option.option.optionExtraType,
            "optionValue": option.optionValue,
        }

        if option.option.optionExtraType == "int":
            val = Decimal(option.optionValue)
            option_dict["quantity"] = int(val)
            option_dict["total"] = option.option.optionPrice * val

        out.append(option_dict)
    return out


def build_result(cart):
    badges = []
    for pk in cart:
        try:
            badge = Badge.objects.get(id=pk)
            badges.append(badge)
        except Badge.DoesNotExist:
            cart.remove(pk)
            logger.error(
                "ID {0} was in cart but doesn't exist in the database".format(pk)
            )

    order = None
    subtotal = 0
    total_discount = 0
    result = []
    orders = set()
    for badge in badges:
        oi = badge.getOrderItems()
        level = None
        level_subtotal = 0
        attendee_options = []
        effectiveLevel = None
        for item in oi:
            level = item.priceLevel
            attendee_options.append(get_line_items(item.getOptions()))
            level_subtotal += get_order_item_option_total(item.getOptions())

            if level:
                effectiveLevel = {"name": level.name, "price": level.basePrice}
                level_subtotal += level.basePrice

        subtotal += level_subtotal

        order = badge.getOrder()
        orders.add(order)

        holdType = None
        if badge.attendee.holdType:
            holdType = badge.attendee.holdType.name

        level_discount = (
            Decimal(get_discount_total(order.discount, level_subtotal) * 100)
            * TWOPLACES
        )
        total_discount += level_discount

        staff_data = None

        if badge.abandoned == Badge.STAFF:
            staff = Staff.objects.get(event=badge.event, attendee=badge.attendee)

            staff_data = {
                "shirtSize": staff.shirtsize.name if staff.shirtsize else None,
            }

        item = {
            "id": badge.id,
            "firstName": badge.attendee.preferredName or badge.attendee.firstName,
            "lastName": badge.attendee.lastName,
            "badgeName": badge.badgeName,
            "badgeNumber": badge.badgeNumber,
            "abandoned": badge.abandoned,
            "effectiveLevel": effectiveLevel,
            "discount": get_discount_dict(order.discount),
            "age": get_attendee_age(badge.attendee),
            "holdType": holdType,
            "level_subtotal": level_subtotal,
            "level_discount": level_discount,
            "level_total": level_subtotal - level_discount,
            "attendee_options": attendee_options,
            "printed": badge.printed,
            "reference": order.reference,
            "checkedInDate": order.checkedInDate,
            "wristBandCountPickedUp": order.wristBandCountPickedUp,
            "cabinAssignment": order.cabinAssignment,
            "campsiteAssignment": order.campsiteAssignment,
            "staff": staff_data,
        }
        result.append(item)

    total = subtotal
    paid = Decimal(0)

    charityDonation = 0
    orgDonation = 0

    for order in orders:
        total += order.orgDonation + order.charityDonation
        paid += order.total if order.billingType != Order.UNPAID and order.status in (Order.CAPTURED, Order.COMPLETED) else 0

        charityDonation += order.charityDonation
        orgDonation += order.orgDonation

    data = {
        "success": True,
        "result": result,
        "subtotal": subtotal,
        "total": total - total_discount,
        "total_discount": total_discount,
        "charityDonation": charityDonation,
        "orgDonation": orgDonation,
        "paid": paid,
    }

    if order is not None:
        data["order_id"] = order.id
        data["reference"] = order.reference
    else:
        data["order_id"] = None
        data["reference"] = None

    return data


@staff_member_required
def onsite_admin_cart(request):
    # Returns dataset to render onsite cart preview
    request.session["heartbeat"] = time.time()  # Keep session alive
    cart = request.session.get("cart", [])

    data = build_result(cart)

    terminal_data = {
        "updateCart": {
            "cart": {
                "badges": list(map(lambda badge: {
                    "id": badge["id"],
                    "firstName": badge["firstName"],
                    "lastName": badge["lastName"],
                    "badgeName": badge["badgeName"],
                    "effectiveLevel": {
                        "name": badge["effectiveLevel"]["name"],
                        "price": str(badge["level_subtotal"]),
                    },
                    "discountedPrice": str(badge["level_total"]),
                }, data["result"])),
                "charityDonation": str(data["charityDonation"]),
                "organizationDonation": str(data["orgDonation"]),
                "totalDiscount": str(data["total_discount"]),
                "total": str(data["total"]),
                "paid": str(data["paid"]),
            }
        }
    }

    send_mqtt_message_to_terminal(request, terminal_data)

    return JsonResponse(data)


@staff_member_required
def onsite_add_to_cart(request):
    id = request.GET.get("id", None)
    return onsite_add_id_to_cart(request, id)


def onsite_add_id_to_cart(request, id):
    if id is None or id == "":
        return JsonResponse(
            {"success": False, "reason": "Need ID parameter"}, status=400
        )

    try:
        badge = Badge.objects.get(id=id)
    except ValueError:
        return JsonResponse(
            {"success": False, "reason": "ID parameter must be integer"}, status=400
        )

    cart = request.session.get("cart", [])

    order_item = OrderItem.objects.filter(badge=badge, order__isnull=False).first()
    if order_item:
        order_items = OrderItem.objects.filter(order=order_item.order, badge__isnull=False)
        for order_item in order_items:
            if order_item.badge_id not in cart:
                cart.append(order_item.badge_id)

    request.session["cart"] = cart

    return JsonResponse({"success": True, "cart": cart})


@staff_member_required
def onsite_remove_from_cart(request):
    id = request.GET.get("id", None)
    if id is None or id == "":
        return JsonResponse(
            {"success": False, "reason": "Need ID parameter"}, status=400
        )

    try:
        id = int(id)
    except ValueError:
        return JsonResponse(
            {"success": False, "reason": "ID parameter must be integer"}, status=400
        )

    cart = request.session.get("cart", None)
    if cart is None:
        return JsonResponse({"success": False, "reason": "Cart is empty"})

    try:
        cart.remove(id)
        request.session["cart"] = cart
    except ValueError:
        return JsonResponse({"success": False, "cart": cart, "reason": "Not in cart"})

    return JsonResponse({"success": True, "cart": cart})


@staff_member_required
def onsite_admin_clear_cart(request):
    request.session["cart"] = []
    send_mqtt_message_to_terminal(request, {"clearCart": {}})
    return JsonResponse({"success": True, "cart": []})


@staff_member_required
def onsite_admin_transfer_cart(request):
    terminal_id = request.GET.get("terminal_id")
    badge_ids = request.GET.getlist("badge_id")

    firebase = Firebase.objects.get(id=terminal_id)

    topic = f'{mqtt.get_topic("admin", firebase.name)}/transfer'
    mqtt.send_mqtt_message(topic, {
        "badgeIds": [int(badge_id) for badge_id in badge_ids],
    })

    return JsonResponse({"success": True})


def get_b32_uuid():
    uid = base64.b32encode(uuid.uuid4().bytes).decode("ascii")
    return uid[:26]


@staff_member_required
@permission_required("order.discount")
def create_discount(request):
    # e.g '$10.00' or '10%'
    amount = request.POST.get("amount").strip()
    amount_off = Decimal("0")
    percent_off = 0

    try:
        if amount.startswith("$"):
            amount_off = Decimal(amount[1:])
        elif amount.startswith("%"):
            percent_off = int(amount[1:])
        elif amount.endswith("%"):
            percent_off = int(amount[:-1])
        else:
            return JsonResponse({"success": False, "reason": "Unknown discount type"}, status=400)
    except ValueError as e:
        return JsonResponse({"success": False, "reason": str(e)}, status=400)

    cart = request.session.get("cart", None)
    if cart is None:
        request.session["cart"] = []
        return JsonResponse(
            {"success": False, "reason": "Cart not initialized"}, status=400
        )

    discount = Discount(
        codeName=get_b32_uuid(),
        percentOff=percent_off,
        amountOff=amount_off,
        startDate=timezone.now(),
        endDate=timezone.now() + timedelta(hours=1),
        notes=f"Applied by [{request.user}]",
        oneTime=True,
        used=0,
        reason="Onsite admin discount",
    )
    discount.save()

    # Combine cart orders and apply discount to combined order
    badges = Badge.objects.filter(pk__in=cart)
    orders = [badge.getOrder() for badge in badges]
    combine_orders(orders)

    orders[0].discount = discount
    orders[0].save()

    return JsonResponse({"success": True})


@staff_member_required
def onsite_print_clear(request):
    id = request.GET.get("id", None)
    if id is None or id == "":
        return JsonResponse(
            {"success": False, "reason": "Need ID parameter"}, status=400
        )

    try:
        id = int(id)
    except ValueError:
        return JsonResponse(
            {"success": False, "reason": "ID parameter must be integer"}, status=400
        )

    badge = Badge.objects.get(id=id)
    badge.printed = False
    badge.save()

    return JsonResponse({"success": True})


@csrf_exempt
def terminal_square_token(request):
    key = request.headers.get("authorization").removeprefix("Bearer ")

    try:
        terminal = Firebase.objects.get(token=key)
    except Firebase.DoesNotExist:
        return JsonResponse(
            {"success": False, "reason": "Incorrect API key"}, status=401
        )

    base_url = "https://connect.squareup.com"
    if settings.SQUARE_ENVIRONMENT == "sandbox":
        base_url = "https://connect.squareupsandbox.com"

    scopes = ["MERCHANT_PROFILE_READ", "PAYMENTS_WRITE", "PAYMENTS_WRITE_IN_PERSON"]
    state = get_token(64)

    url = f"{base_url}/oauth2/authorize?client_id={settings.SQUARE_APPLICATION_ID}&state={state}&scope={'+'.join(scopes)}"

    topic = f"{mqtt.get_topic('admin', terminal.name)}/authorize_terminal"
    mqtt.send_mqtt_message(topic, payload={
        "url": url,
        "state": state,
    })

    return JsonResponse(True, safe=False)

def oauth_square(request):
    url_state = request.GET.get("state")
    cookie_state = request.COOKIES.get("square_oauth_state")

    if url_state != cookie_state:
        return JsonResponse({"success": False, "reason": "Saved state did not match URL state"}, status=400)

    code = request.GET.get("code")

    result = payments.client.o_auth.obtain_token({
        "client_id": settings.SQUARE_APPLICATION_ID,
        "client_secret": settings.SQUARE_APPLICATION_SECRET,
        "code": code,
        "grant_type": "authorization_code"
    })

    if result.is_success():
        send_mqtt_message_to_terminal(request, {
            "updateToken": {
                "accessToken": result.body["access_token"],
                "refreshToken": result.body["refresh_token"]
            }
        })
        resp = HttpResponseRedirect(reverse("registration:onsite_admin"))
    else:
        print(result.errors)
        resp = JsonResponse({"success": False, "reason": "Could not fetch tokens"})

    resp.delete_cookie("square_oauth_state")
    return resp


def print_receipts(request):
    terminal = get_active_terminal(request)
    if not terminal:
        return JsonResponse({"success": False, "reason": "No terminal attached to session"}, status=400)

    references = request.GET.getlist("reference", [])
    orders = Order.objects.filter(reference__in=references).prefetch_related()

    for order in orders:
        if order.billingType in (Order.UNPAID, Order.COMP):
            continue

        if order.billingType == Order.CASH:
            try:
                note_data = json.loads(order.notes)
            except:
                return JsonResponse({"success": False, "reason": "Cash order was missing note data"})

            payload = cash_receipt_payload(order, note_data["tendered"], order.total)
            topic = f"{mqtt.get_topic('receipts', terminal.name)}/print_cash"
            mqtt.send_mqtt_message(topic, payload)

        elif order.billingType == Order.CREDIT:
            if not order.apiData or "payment" not in order.apiData:
                return JsonResponse({"success": False, "reason": "Missing payment data on credit transaction"})

            if not payments.print_payment_receipt(request, terminal.square_terminal_id, order.apiData["payment"]["id"]):
                return JsonResponse({"success": False, "reason": "Got error attempting to print receipt"})

    return JsonResponse({"success": True})
