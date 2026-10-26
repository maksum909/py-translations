"""Time JSON and table reads. Not part of CI.

    python benchmarks/bench.py --n 10000

The two columns are this package's backends on the same SQLite database.
"""

from __future__ import annotations

import argparse
import os
import time


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")
    import django
    from django.core.management import call_command

    django.setup()
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=10_000)
    count = parser.parse_args().n

    from tests.testapp.models import Article, Page

    call_command("migrate", run_syncdb=True, verbosity=0)
    json_write, json_read = _bench(Article, count, "j")
    table_write, table_read = _bench(Page, count, "t")
    print(f"rows: {count}")
    print(f"json  write {json_write:.3f}s  read {json_read:.3f}s")
    print(f"table write {table_write:.3f}s  read {table_read:.3f}s")


def _bench(model, count: int, prefix: str) -> tuple[float, float]:
    started = time.perf_counter()
    for index in range(count):
        row = model(slug=f"{prefix}{index}")
        row.set_translation("en", title="Hello", body="Body")
        row.set_translation("uk", title="Привіт", body="Тіло")
        row.save()
    write = time.perf_counter() - started
    started = time.perf_counter()
    list(model.objects.translated("uk").filter(title="Привіт"))
    return write, time.perf_counter() - started


if __name__ == "__main__":
    main()
