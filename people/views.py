from rest_framework.viewsets import ReadOnlyModelViewSet

from .models import Person
from .serializers import PersonSerializer


class PersonViewSet(ReadOnlyModelViewSet):
    """Entirely stock DRF + drf-datatables — no custom filtering or pagination.

    The DataTables search box becomes ``full_name__icontains`` via the default
    ``DatatablesFilterBackend``; the default pagination class (subclassed only
    to add a log line) supplies the count-clamped ``LIMIT``.
    """

    queryset = Person.objects.all()
    serializer_class = PersonSerializer
