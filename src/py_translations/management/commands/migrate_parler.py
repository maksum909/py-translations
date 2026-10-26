from collections import defaultdict

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError

from py_translations.models import TranslatableModel
from py_translations.storage import field_names


class Command(BaseCommand):
    help = "Copy django-parler translation rows into py_translations storage."

    def add_arguments(self, parser):
        parser.add_argument("--from-model", required=True, help="app_label.ParlerTranslationModel")
        parser.add_argument("--to-model", required=True, help="app_label.TranslatableModel")
        parser.add_argument("--master-field", default="master")
        parser.add_argument("--language-field", default="language_code")
        parser.add_argument("--chunk-size", type=int, default=500)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        source = apps.get_model(options["from_model"])
        target = apps.get_model(options["to_model"])
        if not issubclass(target, TranslatableModel):
            raise CommandError(f"{target._meta.label} is not a TranslatableModel.")
        master_field = options["master_field"]
        language_field = options["language_field"]
        try:
            source._meta.get_field(master_field)
            source._meta.get_field(language_field)
        except Exception as exc:
            raise CommandError(
                f"{source._meta.label} needs '{master_field}' and '{language_field}' fields."
            ) from exc

        names = [name for name in field_names(target) if _has_field(source, name)]
        if not names:
            raise CommandError("No translated field names overlap between the two models.")

        master_attname = source._meta.get_field(master_field).attname
        grouped: dict[int, list] = defaultdict(list)
        for row in source.objects.order_by(master_attname).iterator(
            chunk_size=options["chunk_size"]
        ):
            grouped[getattr(row, master_attname)].append(row)

        written = 0
        missing = 0
        for master_id, rows in grouped.items():
            try:
                instance = target._default_manager.get(pk=master_id)
            except target.DoesNotExist:
                missing += 1
                self.stderr.write(f"Missing {target.__name__} pk={master_id}, skipped.")
                continue
            for row in rows:
                payload = {name: getattr(row, name) for name in names}
                instance.set_translation(getattr(row, language_field), **payload)
            if not options["dry_run"]:
                instance.save()
            written += len(rows)

        label = "Would copy" if options["dry_run"] else "Copied"
        self.stdout.write(f"{label} {written} translation row(s); missing masters: {missing}.")


def _has_field(model, name: str) -> bool:
    try:
        model._meta.get_field(name)
    except Exception:
        return False
    return True
