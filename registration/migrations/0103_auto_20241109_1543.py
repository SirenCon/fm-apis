# Generated by Django 3.2.25 on 2024-11-09 20:43

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('registration', '0102_event_dealer_wifi_partner_price'),
    ]

    operations = [
        migrations.CreateModel(
            name='BadgeTemplate',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('template', models.TextField()),
                ('paperWidth', models.CharField(max_length=10, null=True)),
                ('paperHeight', models.CharField(max_length=10, null=True)),
                ('marginTop', models.CharField(max_length=10, null=True)),
                ('marginBottom', models.CharField(max_length=10, null=True)),
                ('marginLeft', models.CharField(max_length=10, null=True)),
                ('marginRight', models.CharField(max_length=10, null=True)),
                ('landscape', models.BooleanField(default=True)),
                ('scale', models.FloatField(default=1.0)),
            ],
        ),
        migrations.AddField(
            model_name='event',
            name='defaultBadgeTemplate',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='registration.badgetemplate'),
        ),
    ]