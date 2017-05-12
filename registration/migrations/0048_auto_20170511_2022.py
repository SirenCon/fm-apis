# -*- coding: utf-8 -*-
# Generated by Django 1.9.8 on 2017-05-12 00:22
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion
import registration.models


class Migration(migrations.Migration):

    dependencies = [
        ('registration', '0047_auto_20170428_2054'),
    ]

    operations = [
        migrations.CreateModel(
            name='Badge',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('registeredDate', models.DateTimeField(null=True)),
                ('registrationToken', models.CharField(default=registration.models.getRegistrationToken, max_length=200)),
                ('badgeName', models.CharField(blank=True, max_length=200)),
                ('badgeNumber', models.IntegerField(blank=True, null=True)),
                ('printed', models.BooleanField(default=False)),
                ('attendee', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='registration.Attendee')),
                ('event', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='registration.Event')),
            ],
        ),
        migrations.RemoveField(
            model_name='priceleveloption',
            name='priceLevel',
        ),
        migrations.AddField(
            model_name='pricelevel',
            name='priceLevelOptions',
            field=models.ForeignKey(default=1, on_delete=django.db.models.deletion.CASCADE, to='registration.PriceLevelOption'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='priceleveloption',
            name='optionExtraType2',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='priceleveloption',
            name='optionExtraType3',
            field=models.CharField(blank=True, max_length=100),
        ),
    ]
