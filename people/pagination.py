import logging

from rest_framework_datatables.pagination import DatatablesPageNumberPagination

logger = logging.getLogger(__name__)


class LoggingDatatablesPagination(DatatablesPageNumberPagination):
    """Stock DataTables pagination plus one log line exposing the LIMIT clamp.

    ``DatatablesFilterBackend`` stores the filtered count on the view before
    pagination runs. ``django.core.paginator.Paginator.page()`` then clamps the
    page slice to that count (``top = self.count`` when
    ``top + orphans >= self.count``), so a filtered count smaller than the
    requested page length becomes the SQL ``LIMIT`` of the page query. The log
    line records both numbers *before* the page query executes — when the bug
    bites, the request stalls immediately after this line is printed.
    """

    def paginate_queryset(self, queryset, request, view=None):
        filtered_count = getattr(view, "_datatables_filtered_count", None)
        page_size = self.get_page_size(request)
        if filtered_count is not None and page_size:
            effective_limit = min(page_size, filtered_count)
            logger.info(
                "pagination clamp: client requested length=%s, filtered count=%s "
                "-> page query will run with LIMIT %s",
                page_size,
                filtered_count,
                effective_limit,
            )
        return super().paginate_queryset(queryset, request, view)
