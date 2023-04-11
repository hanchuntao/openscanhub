# Generated by Django 2.2.24 on 2023-04-03 23:06

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('scan', '0006_auto_20230329_1348'),
        ('waiving', '0003_auto_20230328_1310'),
    ]

    operations = [
        migrations.CreateModel(
            name='JiraBug',
            fields=[
                ('key', models.CharField(max_length=64, primary_key=True, serialize=False)),
                ('package', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='scan.Package')),
                ('release', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='scan.SystemRelease')),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.AddField(
            model_name='waiver',
            name='jira_bug',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='waiving.JiraBug'),
        ),
    ]
