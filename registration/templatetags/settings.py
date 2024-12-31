# Make attributes from settings.py available to templates

from django import template
from django.conf import settings

register = template.Library()


@register.simple_tag
def settings_value(name, default=""):
    return getattr(settings, name, default)


@register.simple_tag
def settings_value_bool(name):
    setting = getattr(settings, name, False)
    if setting:
        return "true"
    return "false"
