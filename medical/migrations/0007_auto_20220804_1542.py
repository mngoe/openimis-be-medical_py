# Generated by Django 3.0.14 on 2022-08-04 15:42

import core.fields
import datetime
from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('medical', '0006_auto_20220804_1410'),
    ]

    operations = [
        migrations.RenameField(
            model_name='serviceitem',
            old_name='servicelinked',
            new_name='servicelinkedItem',
        ),
        migrations.RenameField(
            model_name='serviceservice',
            old_name='servicelinked',
            new_name='servicelinkedService',
        ),
    ]