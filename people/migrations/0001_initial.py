import django.contrib.postgres.indexes
import django.db.models.functions.text
from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        TrigramExtension(),
        migrations.CreateModel(
            name="Person",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("full_name", models.CharField(max_length=500)),
            ],
        ),
        migrations.AddIndex(
            model_name="person",
            index=models.Index(fields=["full_name"], name="person_full_name_idx"),
        ),
        migrations.AddIndex(
            model_name="person",
            index=django.contrib.postgres.indexes.GinIndex(
                django.contrib.postgres.indexes.OpClass(
                    django.db.models.functions.text.Upper("full_name"),
                    name="gin_trgm_ops",
                ),
                name="person_full_name_trgm_idx",
            ),
        ),
    ]
