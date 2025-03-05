from pathlib import Path
import sys

from django.conf import settings
from django.core.management.base import BaseCommand

from registration.utils.database import DatabaseStatus, Postgres


class Command(BaseCommand):
    help = "Starts the development postgresql database."

    def add_arguments(self, parser):
        if not (db_dir := getattr(settings, "PGDB_PATH")):
            base_dir = Path(settings.BASE_DIR)
            db_dir = (base_dir / "pgdb").absolute()

        parser.add_argument(
            "--db-path",
            type=str,
            default=str(db_dir),
            help=f"Path where the postgresql database will be stopped, default {db_dir}.",
        )
        parser.add_argument(
            "--db-name",
            type=str,
            default="apis_dev",
            help="The database name to create, default apis_dev.",
        )
        parser.add_argument(
            "--test-db-name",
            type=str,
            default="apis_test",
            help="The test database name to create, default apis_test.",
        )
        parser.add_argument(
            "--skip-test-db",
            type=bool,
            default=False,
            help="Whether or not to skip creating the test database, default False.",
        )

    def handle(self, *args, **options):
        postgres = Postgres(options["db_path"])

        status = postgres.get_status()
        if status == DatabaseStatus.STOPPED:
            postgres.start()

            print("Postgres server started")
        elif status == DatabaseStatus.RUNNING:
            print("Postgres server is already running")
        else:
            print(f"Cannot start Postgres server, invalid status: {status}", file=sys.stderr)
            return

        db_name = options["db_name"]
        postgres.create_db(db_name)

        skip_test_db = options["skip_test_db"]
        test_db_name = options["test_db_name"]
        if test_db_name and not skip_test_db:
            postgres.create_db(test_db_name)
