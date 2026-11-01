from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("base", "__first__"),
    ]

    operations = [
        migrations.CreateModel(
            name="QualityReport",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("checked", models.DateTimeField(auto_now=True)),
                (
                    "status",
                    models.CharField(
                        choices=[("ok", "No issues"), ("warnings", "Warnings"), ("problems", "Problems")], max_length=16
                    ),
                ),
                ("summary", models.CharField(max_length=255)),
                ("report", models.JSONField(default=dict)),
                (
                    "resource",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="avdp_quality",
                        to="base.resourcebase",
                    ),
                ),
            ],
            options={"verbose_name": "AVDP data check"},
        ),
    ]
