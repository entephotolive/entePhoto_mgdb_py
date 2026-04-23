from django.core.management.base import BaseCommand, CommandError

from config.mongo import assert_database_ready


class Command(BaseCommand):
    help = "Verify the MongoDB Atlas connection and create the required indexes."

    def handle(self, *args, **options):
        try:
            assert_database_ready()
        except Exception as exc:  # noqa: BLE001
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS("MongoDB Atlas connection is healthy and indexes are ready."))
