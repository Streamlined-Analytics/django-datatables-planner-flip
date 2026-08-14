from django.core.management.base import BaseCommand
from django.db import connection

BATCH_SIZE = 1_000_000

FIRST_NAMES = (
    "James John Robert Michael William David Richard Joseph Thomas Charles "
    "Christopher Daniel Matthew Anthony Mark Donald Steven Paul Andrew Joshua "
    "Kenneth Kevin Brian George Edward Ronald Timothy Jason Jeffrey Ryan "
    "Jacob Gary Nicholas Eric Jonathan Stephen Larry Justin Scott Brandon "
    "Benjamin Samuel Gregory Frank Alexander Raymond Patrick Jack Dennis Jerry "
    "Mary Patricia Jennifer Linda Elizabeth Barbara Susan Jessica Sarah Karen "
    "Nancy Lisa Betty Margaret Sandra Ashley Kimberly Emily Donna Michelle "
    "Dorothy Carol Amanda Melissa Deborah Stephanie Rebecca Sharon Laura Cynthia "
    "Kathleen Amy Shirley Angela Helen Anna Brenda Pamela Nicole Emma "
    "Samantha Katherine Christine Debra Rachel Catherine Carolyn Janet Ruth Maria "
    "Heather Diane Virginia Julie Joyce Victoria Olivia Kelly Christina Lauren "
    "Joan Evelyn Judith Megan Cheryl Andrea Hannah Martha Jacqueline Frances"
).split()

LAST_NAMES = (
    "Smith Johnson Williams Brown Jones Garcia Miller Davis Rodriguez Martinez "
    "Hernandez Lopez Gonzalez Wilson Anderson Thomas Taylor Moore Jackson Martin "
    "Lee Perez Thompson White Harris Sanchez Clark Ramirez Lewis Robinson "
    "Walker Young Allen King Wright Scott Torres Nguyen Hill Flores "
    "Green Adams Nelson Baker Hall Rivera Campbell Mitchell Carter Roberts "
    "Gomez Phillips Evans Turner Diaz Parker Cruz Edwards Collins Reyes "
    "Stewart Morris Morales Murphy Cook Rogers Gutierrez Ortiz Morgan Cooper "
    "Peterson Bailey Reed Kelly Howard Ramos Kim Cox Ward Richardson "
    "Watson Brooks Chavez Wood James Bennett Gray Mendoza Ruiz Hughes "
    "Price Alvarez Castillo Sanders Patel Myers Long Ross Foster Jimenez "
    "Powell Jenkins Perry Russell Sullivan Bell Coleman Butler Henderson Barnes "
    "Gibson Ellis Fisher Reynolds Owens Simmons Porter Hunter Hicks Crawford "
    "Boyd Mason Holmes Warren Dixon Bootman Bootle Booth Bootham Ramsbottom "
    "Higginbotham Winterbourne Ashworth Ollerenshaw Postlethwaite Featherstone "
    "Micklethwaite Sidebottom Arkwright Entwistle Hebblethwaite Outhwaite"
).split()


class Command(BaseCommand):
    help = (
        "Bulk-seed the people_person table with generated names, plus a rare "
        "name seeded a handful of times. Idempotent: truncates first."
    )

    def add_arguments(self, parser):
        parser.add_argument("--rows", type=int, default=10_000_000)
        parser.add_argument("--rare-name", default="Ronald Quibble")
        parser.add_argument("--rare-count", type=int, default=7)

    def handle(self, *, rows, rare_name, rare_count, **options):
        with connection.cursor() as cursor:
            index_defs = self._saved_index_definitions(cursor)
            self._drop_indexes(cursor, index_defs)

            cursor.execute("TRUNCATE people_person RESTART IDENTITY")
            self._insert_generated_rows(cursor, rows)
            cursor.execute(
                "INSERT INTO people_person (full_name)"
                " SELECT %s FROM generate_series(1, %s)",
                [rare_name, rare_count],
            )
            self.stdout.write(f"inserted {rare_count} x {rare_name!r}")

            self._recreate_indexes(cursor, index_defs)
            self.stdout.write("running ANALYZE ...")
            cursor.execute("ANALYZE people_person")

        self.stdout.write(self.style.SUCCESS(f"seeded {rows + rare_count} rows"))

    def _saved_index_definitions(self, cursor):
        """The non-PK index DDL, captured so the load can run unindexed.

        Re-executing pg_get_indexdef output guarantees the recreated indexes
        are byte-identical to what the migration built.
        """
        cursor.execute(
            "SELECT indexname, indexdef FROM pg_indexes"
            " WHERE tablename = 'people_person' AND indexname NOT LIKE %s",
            ["%pkey"],
        )
        return cursor.fetchall()

    def _drop_indexes(self, cursor, index_defs):
        for name, _ in index_defs:
            cursor.execute(f'DROP INDEX IF EXISTS "{name}"')
        self.stdout.write(f"dropped {len(index_defs)} indexes for the load")

    def _insert_generated_rows(self, cursor, rows):
        """Names are FIRST [initial.] LAST from the arrays, cycled by row number.

        Every third row gets a middle initial to widen the distinct-name space.
        The rare name's surname must not appear in LAST_NAMES.
        """
        insert_sql = (
            "INSERT INTO people_person (full_name)"
            " SELECT (%s::text[])[1 + (g %% %s)]"
            "        || CASE WHEN g %% 3 = 0"
            "                THEN ' ' || substr('ABCDEFGHIJKLMNOPQRSTUVWXYZ', 1 + (g %% 26), 1) || '.'"
            "                ELSE '' END"
            "        || ' ' || (%s::text[])[1 + ((g / 7) %% %s)]"
            " FROM generate_series(%s, %s) AS g"
        )
        for start in range(0, rows, BATCH_SIZE):
            stop = min(start + BATCH_SIZE, rows) - 1
            cursor.execute(
                insert_sql,
                [FIRST_NAMES, len(FIRST_NAMES), LAST_NAMES, len(LAST_NAMES), start, stop],
            )
            self.stdout.write(f"inserted rows {start:,} .. {stop:,}")

    def _recreate_indexes(self, cursor, index_defs):
        cursor.execute("SET maintenance_work_mem = '512MB'")
        for name, definition in index_defs:
            self.stdout.write(f"recreating {name} ...")
            cursor.execute(definition)
