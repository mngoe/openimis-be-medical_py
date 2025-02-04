# Generated by Django 3.0.14 on 2022-08-05 21:08

import core.fields
import datetime
from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('medical', '0007_auto_20220804_1542'),
    ]

    operations = [
        migrations.RenameField(
            model_name='serviceitem',
            old_name='item_id',
            new_name='item',
        ),
        migrations.AddField(
            model_name='serviceitem',
            name='status',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='serviceservice',
            name='status',
            field=models.BooleanField(default=True),
        ),
    ]
