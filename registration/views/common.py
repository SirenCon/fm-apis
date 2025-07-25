import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional, Tuple

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import user_passes_test
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Q
from django.db.models.fields.files import FieldFile
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import cache_page
from idempotency_key.decorators import idempotency_key

import registration.emails
from registration.models import (
    Cart,
    Department,
    Discount,
    Event,
    Order,
    OrderItem,
    PriceLevel,
    PriceLevelOption,
    ShirtSizes,
    Staff,
    get_token,
)
from registration.payments import charge_payment
from registration.views import ordering
from registration.views.cart import saveCart
from registration.views.ordering import add_attendee_to_assistant

logger = logging.getLogger("django.request")


def flush(request):
    clear_session(request)
    return JsonResponse({"success": True})


def in_group(groupname):
    def inner(user):
        return user.groups.filter(name=groupname).exists()

    return inner


def clear_session(request):
    """
    Soft-clears session by removing any non-protected session values.
    (anything prefixed with '_'; keeps Django user logged-in)
    """
    for key in list(request.session.keys()):
        if key[0] != "_":
            del request.session[key]
            logger.debug(f"Delete session key {key}")
    request.session.save()


def get_client_ip(request):
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        ip = x_forwarded_for.split(",")[0]
    else:
        ip = request.META.get("REMOTE_ADDR")
    return ip


def get_request_meta(request):
    values = {}
    values["HTTP_REFERER"] = request.META.get("HTTP_REFERER")
    values["HTTP_USER_AGENT"] = request.META.get("HTTP_USER_AGENT")
    values["IP"] = get_client_ip(request)
    return json.dumps(values)


def getOptionsDict(orderItems):
    orderDict = []
    for oi in orderItems:
        aos = oi.getOptions()
        for ao in aos:
            orderDict.append(
                {
                    "name": ao.option.optionName,
                    "type": ao.option.optionExtraType,
                    "value": ao.optionValue,
                    "id": ao.option.id,
                    "image": ao.option.getOptionImage(),
                }
            )

    return orderDict


@cache_page(60)
def get_events(request):
    events = Event.objects.all()
    data = [
        {
            "name": ev.name,
            "id": ev.id,
            "dealerStart": ev.dealerRegStart,
            "dealerEnd": ev.dealerRegEnd,
            "staffStart": ev.staffRegStart,
            "staffEnd": ev.staffRegEnd,
            "attendeeStart": ev.attendeeRegStart,
            "attendeeEnd": ev.attendeeRegEnd,
        }
        for ev in events
    ]
    return HttpResponse(
        json.dumps(data, cls=DjangoJSONEncoder), content_type="application/json"
    )


def abort(status=400, reason="Bad request"):
    """
    Returns a JSON response indicating an error to the client.

    status: A valid HTTP status code
    reason: Human-readable explanation
    """
    logger.info("JSON {0}: {1}".format(status, reason))
    return JsonResponse({"success": False, "reason": reason}, status=status)


def success(status=200, reason=None):
    """
    Returns a JSON response indicating success.

    status: A valid HTTP status code (2xx)
    reason: (Optional) human-readable explanation
    """
    if reason is None:
        logger.debug("JSON {0}".format(status))
        return JsonResponse({"success": True}, status=status)
    else:
        logger.debug("JSON {0}: {1}".format(status, reason))
        return JsonResponse(
            {
                "success": True,
                "reason": reason,
                "message": reason,  # Backwards compatibility
            },
            status=status,
        )


def get_confirmation_token():
    return get_token(6)


def get_unique_confirmation_token(model):
    reference = get_confirmation_token()
    while model.objects.filter(reference=reference).exists():
        reference = get_confirmation_token()
    return reference


def handler(obj):
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    elif isinstance(obj, Decimal):
        return str(obj)
    elif isinstance(obj, FieldFile):
        try:
            return obj.url
        except ValueError:
            return None
    else:
        raise TypeError(
            "Object of type %s with value of %s is not JSON serializable"
            % (
                type(obj),
                repr(obj),
            )
        )

def _get_default_non_vendor_price_level(now: datetime) -> Optional[int]:
    price_levels = PriceLevel.objects.filter(
        public=True, startDate__lte=now, endDate__gte=now
    ).all()

    non_vendor_id = None
    for price_level in price_levels:
        if price_level.isVendor:
            continue

        if non_vendor_id is not None:
            # Got more than one non-vendor
            return None

        non_vendor_id = price_level.id

    return non_vendor_id


def _parse_level_id(level_id: Optional[Any], now: datetime) -> Tuple[Optional[int], bool]:
    try:
        level_id = int(level_id)
    except Exception:
        level_id = None

    if level_id is None:
        # Default the non-vendor price level if there's only one
        level_id = _get_default_non_vendor_price_level(now)
        return level_id, False

    # Check if the given level_id is a vendor id
    try:
        price_level = PriceLevel.objects.filter(
            id=level_id, public=True, startDate__lte=now, endDate__gte=now
        ).first()
        is_vendor = price_level.isVendor if price_level else None

        return level_id, is_vendor
    except PriceLevel.DoesNotExist:
        level_id = _get_default_non_vendor_price_level()
        return level_id, False


def index(request):
    level_id = request.GET.get("level_id")

    try:
        event = Event.objects.get(default=True)
    except Event.DoesNotExist:
        return render(request, "registration/docs/no-event.html")

    tz = timezone.get_current_timezone()
    now = timezone.now()
    today = tz.localize(datetime.now())
    discount = request.session.get("discount")
    if discount:
        discount = Discount.objects.filter(codeName=discount)
        if discount.count() > 0:
            discount = discount.first()

    level_count = PriceLevel.objects.filter(
        public=True, startDate__lte=now, endDate__gte=now
    ).order_by("basePrice").count()

    level_id, is_vendor = _parse_level_id(level_id, now)

    context = {
        "event": event,
        "discount": discount,
        "form_type": "attendee",
        "level_count": level_count,
        "selected_price_level": level_id,
        "selected_price_level_is_vendor": is_vendor,
    }

    if event.websiteUrl:
        context["homeRedirect"] = event.websiteUrl
    else:
        context["homeRedirect"] = reverse("registration:index")

    if event.attendeeRegStart <= today <= event.attendeeRegEnd:
        return render(request, "registration/registration-form.html", context)
    elif event.attendeeRegStart >= today:
        context["message"] = "is not yet open. Please stay tuned to our social media for updates!"
        return render(request, "registration/closed.html", context)
    elif event.attendeeRegEnd <= today:
        context["message"] = "has ended. In person registration will open on event day, May 31st, 2025."
        return render(request, "registration/closed.html", context)


@staff_member_required
@user_passes_test(in_group("Manager"))
def manualDiscount(request):
    # FIXME stub
    raise NotImplementedError


@cache_page(60 * 5)
@staff_member_required
def basicBadges(request):
    event = Event.objects.get(default=True)

    staff = Staff.objects.filter(event=event)
    order_items = OrderItem.objects.filter(badge__event=event)

    bdata = [
        {
            "badgeName": oi.badge.badgeName,
            "level": oi.badge.effectiveLevel(),
            "assoc": oi.badge.abandoned,
            "firstName": oi.badge.attendee.firstName.lower(),
            "lastName": oi.badge.attendee.lastName.lower(),
            "printed": oi.badge.printed,
            "discount": oi.badge.getDiscount(),
            "orderItems": getOptionsDict(oi.badge.orderitem_set.all()),
        }
        for oi in order_items
    ]

    staffdata = [
        {
            "firstName": s.attendee.firstName.lower(),
            "lastName": s.attendee.lastName.lower(),
            "title": s.title,
            "id": s.id,
        }
        for s in staff
    ]

    for staff in staffdata:
        sbadge = Staff.objects.get(id=staff["id"]).getBadge()
        if sbadge:
            staff["badgeName"] = sbadge.badgeName
            if sbadge.effectiveLevel():
                staff["level"] = sbadge.effectiveLevel()
            else:
                staff["level"] = "none"
            staff["assoc"] = sbadge.abandoned
            staff["orderItems"] = getOptionsDict(sbadge.orderitem_set.all())

    sdata = sorted(bdata, key=lambda x: (str(x["level"]), x["lastName"]))
    ssdata = sorted(staffdata, key=lambda x: x["lastName"])

    dealers = [att for att in sdata if att["assoc"] == "Dealer"]
    staff = [att for att in ssdata]
    attendees = [att for att in sdata if att["assoc"] != "Staff"]
    return render(
        request,
        "registration/utility/badgelist.html",
        {"attendees": attendees, "dealers": dealers, "staff": staff},
    )


@cache_page(60 * 5)
@staff_member_required
def vipBadges(request):
    default_event = Event.objects.get(default=True)
    event_id = request.GET.get("event", default_event.id)
    event = get_object_or_404(Event, id=event_id)

    # Assumes VIP levels based on being marked as "vip" group, or EmailVIP set
    price_levels = PriceLevel.objects.filter(Q(emailVIP=True) | Q(group__iexact="vip"))
    shirt_sizes = {str(shirt.pk): shirt.name for shirt in ShirtSizes.objects.all()}

    vip_order_items = OrderItem.objects.filter(
        priceLevel__in=price_levels, badge__event=event
    )

    badges = [
        {
            "badge": oi.badge,
            "orderItems": getOptionsDict(oi.badge.orderitem_set.all()),
            "level": oi.badge.effectiveLevel(),
            "assoc": oi.badge.abandoned,
        }
        for oi in vip_order_items
        if oi.badge.abandoned != "Staff"
    ]

    context = {
        "badges": badges,
        "event": event,
        "shirt_sizes": shirt_sizes,
    }

    return render(
        request,
        "registration/utility/viplist.html",
        context,
    )


@cache_page(60)
def get_departments(request):
    depts = Department.objects.filter(volunteerListOk=True).order_by("name")
    data = [{"name": item.name, "id": item.id} for item in depts]
    return HttpResponse(json.dumps(data), content_type="application/json")


@cache_page(60)
def get_all_departments(request):
    depts = Department.objects.order_by("name")
    data = [{"name": item.name, "id": item.id} for item in depts]
    return HttpResponse(json.dumps(data), content_type="application/json")


@cache_page(60)
def get_shirt_sizes(request):
    sizes = ShirtSizes.objects.all()
    data = [{"name": size.name, "id": size.id} for size in sizes]
    return HttpResponse(json.dumps(data), content_type="application/json")


def get_session_addresses(request):
    event = Event.objects.get(default=True)
    sessionItems = request.session.get("cart_items", [])
    if not sessionItems:
        # might be from dealer workflow, which is order items in the session
        sessionItems = request.session.get("order_items", [])
        if not sessionItems:
            data = {}
        else:
            orderItems = OrderItem.objects.filter(id__in=sessionItems)
            data = [
                {
                    "id": oi.badge.attendee.id,
                    "fname": oi.badge.attendee.firstName,
                    "lname": oi.badge.attendee.lastName,
                    "email": oi.badge.attendee.email,
                    "address1": oi.badge.attendee.address1,
                    "address2": oi.badge.attendee.address2,
                    "city": oi.badge.attendee.city,
                    "state": oi.badge.attendee.state,
                    "country": oi.badge.attendee.country,
                    "postalCode": oi.badge.attendee.postalCode,
                }
                for oi in orderItems
            ]
    else:
        data = []
        cartItems = list(Cart.objects.filter(id__in=sessionItems))
        for cart in cartItems:
            cartJson = json.loads(cart.formData)
            pda = cartJson["attendee"]
            cartItem = {
                "fname": pda["firstName"],
                "lname": pda["lastName"],
                "email": pda["email"],
                "phone": pda["phone"],
            }
            if event.collectAddress:
                cartItem.update(
                    {
                        "address1": pda["address1"],
                        "address2": pda["address2"],
                        "city": pda["city"],
                        "state": pda["state"],
                        "postalCode": pda["postal"],
                        "country": pda["country"],
                    }
                )

            data.append(cartItem)
    return HttpResponse(json.dumps(data), content_type="application/json")


def get_registration_email(event=None):
    """
    Retrieves the email address to show on error messages in the attendee
    registration form for a specified event.  If no event specified, uses
    the first default event.  If no email is listed there, returns the
    default of APIS_DEFAULT_EMAIL in settings.py.
    """
    if event is None:
        try:
            event = Event.objects.get(default=True)
        except BaseException:
            return settings.APIS_DEFAULT_EMAIL
    if event.registrationEmail == "":
        return settings.APIS_DEFAULT_EMAIL
    return event.registrationEmail
