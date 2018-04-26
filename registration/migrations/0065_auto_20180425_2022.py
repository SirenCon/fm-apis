# -*- coding: utf-8 -*-
# Generated by Django 1.11.6 on 2018-04-26 00:22
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('registration', '0064_event_default'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='event',
            name='dealerAsstDiscount',
        ),
        migrations.RemoveField(
            model_name='event',
            name='dealerDiscount',
        ),
        migrations.RemoveField(
            model_name='event',
            name='staffDiscount',
        ),
        migrations.AddField(
            model_name='event',
            name='dealerBasePriceLevel',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='registration.PriceLevel'),
        ),
    ]
