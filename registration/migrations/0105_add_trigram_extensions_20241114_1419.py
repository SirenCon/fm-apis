# Generated by Django 3.2.25 on 2024-11-14 19:19

from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('registration', '0104_add_event_website_url'),
    ]

    operations = [
        TrigramExtension()
    ]
