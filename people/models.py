from django.contrib.postgres.indexes import GinIndex, OpClass
from django.db import models
from django.db.models.functions import Upper


class Person(models.Model):
    """The singular model: one row per person, one searchable field.

    The two indexes are the two competing plans:

    - ``person_full_name_idx`` (btree) serves ``ORDER BY full_name`` and is the
      index the planner walks in the slow abort-early plan.
    - ``person_full_name_trgm_idx`` (GIN trigram on ``UPPER(full_name)``) serves
      ``full_name__icontains`` and is the index the planner *should* use.
    """

    full_name = models.CharField(max_length=500)

    class Meta:
        indexes = [
            models.Index(fields=["full_name"], name="person_full_name_idx"),
            GinIndex(
                OpClass(Upper("full_name"), name="gin_trgm_ops"),
                name="person_full_name_trgm_idx",
            ),
        ]

    def __str__(self):
        return self.full_name
