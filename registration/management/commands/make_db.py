from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from registration.utils.database import DatabaseStatus, Postgres


class Command(BaseCommand):
    help = "Creates a development postgresql database."

    def add_arguments(self, parser):
        if not (db_dir := getattr(settings, "PGDB_PATH")):
            base_dir = Path(settings.BASE_DIR)
            db_dir = (base_dir / "pgdb").absolute()

        parser.add_argument(
            "--db-path",
            type=str,
            default=str(db_dir),
            help=f"Path where the postgresql database will be created, default {db_dir}.",
        )
        parser.add_argument(
            "--silent",
            type=bool,
            default=False,
            help="Whether to suppress configuration information, default False."
        )

    def handle(self, *args, **options):
        postgres = Postgres(options["db_path"])

        status = postgres.get_status()

        if status in (DatabaseStatus.UNKNOWN, DatabaseStatus.INVALID_DIRECTORY):
            postgres.delete()

            status = DatabaseStatus.DOES_NOT_EXIST

        if status in (DatabaseStatus.DOES_NOT_EXIST, DatabaseStatus.DIRECTORY_EMPTY):
            postgres.init()

            status = DatabaseStatus.STOPPED

        if options["silent"]:
            return

        print(f"Created database at {postgres.db_path}")
