from django.core.management.base import BaseCommand

from apps.tracking.services import purge_old_points


class Command(BaseCommand):
    help = "Supprime les positions GPS plus anciennes que N jours (conservation à définir avec la compagnie)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=90)

    def handle(self, *args, **opts):
        n = purge_old_points(opts["days"])
        self.stdout.write(self.style.SUCCESS(f"{n} position(s) supprimée(s) (plus de {opts['days']} jours)."))
