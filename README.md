# DataTables pagination clamp → catastrophic Postgres plan flip

A minimal reproduction of a production incident: a server-side DataTables name
search that takes **tens of seconds for rare search terms** and **milliseconds
for common ones** — the more specific the search, the slower it gets.

No custom pagination or filtering code is involved. The entire bug path is:

- [`djangorestframework-datatables`](https://github.com/izimobil/django-rest-framework-datatables) 0.7.2 (stock `DatatablesFilterBackend` + `DatatablesPageNumberPagination`)
- Django 6.0.6 (`django.core.paginator.Paginator.page()`)
- PostgreSQL 18 with `pg_trgm`

## The mechanism in one paragraph

The DataTables filter backend computes the **filtered count first** (cheap — it
has no `ORDER BY`, so it uses the trigram index). The pagination class feeds
that count into a `CachedCountPaginator`, and `Paginator.page()` **clamps the
page slice to the count**: with 7 matches and a requested page length of 25,
`top + orphans >= count` fires and the slice becomes `object_list[0:7]` — i.e.
`LIMIT 7`. That small `LIMIT` is what makes the Postgres planner abandon the
trigram index: it estimates ~2,000 matches for the pattern (actual: 7), assumes
it can walk the ordering btree and stop after `7/2000` of it, prices that walk
below the trigram bitmap plan, and then walks — filtering and discarding
**millions of rows** to find the 7 matches. The cheap count sets the `LIMIT`,
and the `LIMIT` selects the plan. The failure is *inverted*: the rarer the
name, the smaller the count, the smaller the `LIMIT`, the cheaper the
catastrophic walk looks.

## Reproduce it

Requires Docker. The seed creates ~20M rows (a few GB in the `pgdata` volume,
several minutes to load):

```bash
docker compose up -d --build
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py seed_people        # ~20M rows, takes a while
docker compose run --rm web python manage.py demonstrate_flip   # the proof, no browser needed
```

`demonstrate_flip` runs the exact page query under `EXPLAIN (ANALYZE, BUFFERS)`
at `LIMIT 7` (what the clamp produces) and `LIMIT 25` (what the client asked
for). Actual captured output from this repo (only the `LIMIT` differs between
the two queries):

```
=== LIMIT 7 ===    <- the clamped LIMIT the paginator actually emits
Limit  (cost=0.44..3563.06 rows=7) (actual time=59323.994..59323.997 rows=7.00)
  ->  Index Scan using person_full_name_idx on people_person
          (cost=0.44..1010766.80 rows=1986)
        Filter: (upper((full_name)::text) ~~ '%RONALD QUIBBLE%'::text)
        Rows Removed by Filter: 16952382
Execution Time: 59324.033 ms

=== LIMIT 25 ===   <- the LIMIT the client requested
Limit  (cost=10072.95..10073.01 rows=25) (actual time=6.276..6.277 rows=7.00)
  ->  Sort (Sort Key: full_name)
        ->  Bitmap Heap Scan on people_person  (cost=2814.93..10016.90 rows=1986)
              ->  Bitmap Index Scan on person_full_name_trgm_idx
Execution Time: 6.347 ms
```

**59 seconds versus 6 milliseconds, 16.9M rows discarded to return 7** —
faithfully mirroring the production incident (26 s vs 72 ms on 21.8M rows, with
near-identical planner arithmetic: walk-with-LIMIT cost 3,563 here vs 3,558 in
production, row estimate 1,986 vs 2,174).

Then see it end-to-end in the browser at <http://localhost:8000> (set
`WEB_PORT` to remap): search **`ronald quibble`** (the rare seeded name — 7
matches) and the request stalls for a minute; search a common surname like
`anderson` (140k matches) and it returns in about a second. That inversion —
*more specific = catastrophically slower* — is the defining symptom. While the
rare search stalls, the web container log shows the smoking gun, in order:

```
INFO people.pagination pagination clamp: client requested length=25, filtered count=7 -> page query will run with LIMIT 7
DEBUG django.db.backends (63.397) SELECT DISTINCT ... ORDER BY "people_person"."full_name" ASC LIMIT 7
```

(The runtime SQL has a `DISTINCT` the `demonstrate_flip` query omits — the
stock filter backend adds `.distinct()` to searched querysets. It does not
change the plan choice; the walk underneath is identical.)

and `docker compose logs db` shows the full catastrophic plan, captured by
`auto_explain` (enabled in `compose.yml` exactly as it was used to capture the
production incident).

## Where the LIMIT comes from — the code path

1. `rest_framework_datatables.filters.DatatablesFilterBackend` runs the
   filtered `COUNT(*)` and stores it on the view
   (`view._datatables_filtered_count`).
2. `rest_framework_datatables.pagination.DatatablesPageNumberPagination.paginate_queryset`
   reads it back in `get_count_and_total_count()` and builds a
   `CachedCountPaginator` whose `count` property returns the precomputed value —
   [pagination.py](https://github.com/izimobil/django-rest-framework-datatables/blob/master/rest_framework_datatables/pagination.py).
3. `django.core.paginator.Paginator.page()` clamps the slice —
   [paginator.py](https://github.com/django/django/blob/main/django/core/paginator.py):

   ```python
   bottom = (number - 1) * self.per_page
   top = bottom + self.per_page
   if top + self.orphans >= self.count:   # 25 >= 7
       top = self.count                    # top = 7
   return self._get_page(self.object_list[bottom:top], number, self)
   ```

   `object_list[0:7]` → `LIMIT 7`.

None of this is wrong in isolation. The clamp is a reasonable micro-optimisation,
the cached count avoids a second `COUNT(*)`, and the planner's abort-early
arithmetic is sound *if its row estimate is right*. The estimate is ~300× off
(`patternsel` for `%substring%` patterns has almost nothing to go on), and the
three pieces compose into a 26-second query.

## The planner arithmetic (production numbers)

On the production table (21.8M rows) the planner estimated **2,174** matches
for the search pattern; the true count was **7**.

| | cost | outcome |
|---|---|---|
| Full walk of the ordering btree | 1,105,137 | — |
| Walk with `LIMIT 7` (assumes stop after 7/2174) | 1,105,137 × 7/2174 ≈ **3,558** | chosen — 26,182 ms, 17.5M rows discarded |
| Trigram bitmap plan | **4,096** | rejected — 72 ms when forced via `LIMIT 25` |

Note the flip is scale-dependent in an interesting way: the walk-with-LIMIT
cost is *nearly constant* as the table grows (walk cost and row estimate both
scale linearly with table size, so they cancel — ~3,585 at 5M rows, ~3,563 at
20M), while the bitmap plan's cost grows with table size (~2,620 at 5M rows,
~10,073 at 20M). At 5M rows the bitmap plan still wins and there is no bug;
somewhere before 20M the costs cross and the planner flips. That is why this
repo seeds 20M rows.

## The fix we shipped (not included here — this repo is the bug, minimal)

A **count-gated optimisation fence**: when the match count is small (the regime
where the clamp produces a dangerous `LIMIT`), the filter is rewritten as
`pk IN (WITH matches AS MATERIALIZED (SELECT id FROM ... WHERE name LIKE ...) SELECT pk FROM matches)`
— the `MATERIALIZED` CTE is an optimisation barrier, so the trigram lookup can
no longer be traded away against the ordering btree. The gate matters:
fencing *unconditionally* moves the pain to broad terms (a two-letter search
went 102 ms → 23,607 ms fenced), so the fence only applies below a match-count
threshold (10,000), and the gating count is itself capped with `LIMIT N+1`.

## Open questions

- Is `Paginator.page()`'s clamp — turning a cheap count into a plan-selecting
  `LIMIT` — a known footgun with large tables? It seems like a general
  Django-plus-Postgres trap, not specific to DataTables.
- Is there anything to do about `patternsel` being ~300× off for
  `%substring%` patterns, or is "don't let the planner have the choice" the
  only real answer?
- Is there a cleaner idiom than the count-gated fence? (Considered and
  rejected: `text_pattern_ops`/covering indexes, `SET LOCAL enable_indexscan`,
  extended statistics — which don't help `LIKE` — and sorting on a surrogate.)

## Repo layout

| file | role |
|---|---|
| `people/models.py` | one model, one field, the two competing indexes |
| `people/views.py`, `serializers.py` | stock DRF `ReadOnlyModelViewSet` |
| `people/pagination.py` | stock pagination + the clamp log line |
| `people/templates/people/directory.html` | server-side DataTables 1.13.4 frontend |
| `people/management/commands/seed_people.py` | bulk seed (~20M generated names + 7 × the rare name) |
| `people/management/commands/demonstrate_flip.py` | `EXPLAIN ANALYZE` at both LIMITs |
| `compose.yml` | `postgres:18` with `auto_explain`, Django dev server |
