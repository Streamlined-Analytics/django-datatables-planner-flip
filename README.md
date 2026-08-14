# DataTables pagination clamp → catastrophic Postgres plan flip

A server-side DataTables name search that takes **tens of seconds for rare
search terms** and **milliseconds for common ones** — the more specific the
search, the slower it gets. The bug path is entirely stock code:
[`djangorestframework-datatables`](https://github.com/izimobil/django-rest-framework-datatables) 0.7.2,
Django 6.0.6, PostgreSQL 18 with `pg_trgm`.

## Mechanism

1. `DatatablesFilterBackend` computes the filtered count first (cheap — no
   `ORDER BY`, so it uses the trigram index) and stores it on the view.
2. `DatatablesPageNumberPagination` feeds it into a `CachedCountPaginator`, and
   `django.core.paginator.Paginator.page()` clamps the slice: with 7 matches
   and a requested page length of 25, `top + orphans >= count` fires and the
   page query runs with `LIMIT 7` instead of `LIMIT 25`.
3. Postgres estimates ~1,000 matches for the `%substring%` pattern (actual: 7),
   assumes it can walk the ordering btree and stop after `7/1000` of it, prices
   that walk below the trigram bitmap plan — and walks, filtering out millions
   of rows to find the 7 matches.

The cheap count sets the `LIMIT`, and the `LIMIT` selects the plan. No single
component is wrong: the clamp, the cached count, and the abort-early costing
are each reasonable — they compose into the pathology, and it inverts: the
rarer the term, the smaller the `LIMIT`, the cheaper the walk looks.

## Reproduce

Requires Docker. The seed loads ~10M rows (~2 GB, a few minutes):

```bash
docker compose up -d --build
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py seed_people
docker compose run --rm web python manage.py demonstrate_flip
```

`demonstrate_flip` runs the page query under `EXPLAIN (ANALYZE, BUFFERS)` at
both LIMITs. Captured output — only the `LIMIT` differs:

```
=== LIMIT 7 ===    <- what the clamp emits
Limit  (cost=0.43..3566.07 rows=7) (actual time=25826.546..25826.549 rows=7.00)
  ->  Index Scan using person_full_name_idx on people_person
          (cost=0.43..505811.11 rows=993)
        Filter: (upper((full_name)::text) ~~ '%RONALD QUIBBLE%'::text)
        Rows Removed by Filter: 8476192
Execution Time: 25826.587 ms

=== LIMIT 25 ===   <- what the client requested
Limit  (cost=5110.48..5110.54 rows=25) (actual time=0.459..0.459 rows=7.00)
  ->  Sort (Sort Key: full_name)
        ->  Bitmap Heap Scan on people_person  (cost=1481.47..5082.46 rows=993)
              ->  Bitmap Index Scan on person_full_name_trgm_idx
Execution Time: 0.528 ms
```

End-to-end: open <http://localhost:8000> (set `WEB_PORT` to remap), search
**`ronald quibble`** (the rare seeded name, 7 matches) and the request stalls
~30 s; search `anderson` and it returns in ~1 s. The web log shows the clamp:

```
INFO people.pagination pagination clamp: client requested length=25, filtered count=7 -> page query will run with LIMIT 7
DEBUG django.db.backends (32.162) SELECT DISTINCT ... ORDER BY "people_person"."full_name" ASC LIMIT 7
```

(the stock filter backend adds `DISTINCT` to searched querysets; it doesn't
affect the plan choice), and `docker compose logs db` has the full plan via
`auto_explain`.

## Notes

- **Scale threshold:** the walk-with-LIMIT cost is nearly constant as the table
  grows (walk cost and row estimate both scale linearly, so they cancel), while
  the bitmap plan's cost grows with table size. On this seed the plans cross
  between 6.5M and 7M rows — a knife edge there, so the default is 10M for a
  ~43% cost margin. `--rows 20000000` mirrors the production incident this repo
  was distilled from (21.8M rows, 26 s vs 72 ms).
- Any query with this shape and a small `LIMIT` (`.first()`, a "top 5" widget)
  hits the same flip — DataTables is just the delivery mechanism for the
  count-derived `LIMIT`.

## Layout

One model (`people/models.py`: `full_name` plus the btree ordering index and
the trigram search index), a stock DRF `ReadOnlyModelViewSet`, the default
drf-datatables pagination subclassed only to log the clamp
(`people/pagination.py`), a DataTables 1.13.4 frontend, and the two management
commands.
