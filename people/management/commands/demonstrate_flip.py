import re

from django.core.management.base import BaseCommand
from django.db import connection

PAGE_QUERY = (
    'SELECT "people_person"."id", "people_person"."full_name"'
    ' FROM "people_person"'
    ' WHERE UPPER("people_person"."full_name"::text) LIKE UPPER(%s)'
    ' ORDER BY "people_person"."full_name" ASC'
    " LIMIT {limit}"
)


class Command(BaseCommand):
    help = (
        "Run the directory page query under EXPLAIN ANALYZE at two LIMITs to "
        "show the planner flip: the small (clamped) LIMIT picks the abort-early "
        "btree walk, the requested LIMIT picks the trigram bitmap scan."
    )

    def add_arguments(self, parser):
        parser.add_argument("--term", default="ronald quibble")
        parser.add_argument(
            "--limits",
            default="7,25",
            help="Comma-separated LIMIT values to compare (default: 7,25).",
        )
        parser.add_argument("--timeout-ms", type=int, default=300_000)

    def handle(self, *, term, limits, timeout_ms, **options):
        pattern = f"%{term}%"
        with connection.cursor() as cursor:
            cursor.execute("SET statement_timeout = %s", [timeout_ms])
            for limit in (int(value) for value in limits.split(",")):
                plan = self._explain(cursor, limit, pattern)
                self._report(limit, plan)

    def _explain(self, cursor, limit, pattern):
        sql = "EXPLAIN (ANALYZE, BUFFERS) " + PAGE_QUERY.format(limit=limit)
        cursor.execute(sql, [pattern])
        return "\n".join(row[0] for row in cursor.fetchall())

    def _report(self, limit, plan):
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n=== LIMIT {limit} ==="))
        self.stdout.write(plan)
        index_used = "no index?"
        for index_name in ("person_full_name_trgm_idx", "person_full_name_idx"):
            if index_name in plan:
                index_used = index_name
                break
        execution_time = re.search(r"Execution Time: ([\d.]+) ms", plan)
        removed = re.search(r"Rows Removed by Filter: (\d+)", plan)
        summary = (
            f"LIMIT {limit}: used {index_used}, "
            f"execution {execution_time.group(1) if execution_time else '?'} ms"
        )
        if removed:
            summary += f", rows removed by filter {int(removed.group(1)):,}"
        style = (
            self.style.ERROR
            if index_used == "person_full_name_idx"
            else self.style.SUCCESS
        )
        self.stdout.write(style(summary))
