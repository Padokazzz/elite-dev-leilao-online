from django.core.management.base import BaseCommand

from auctions.services import settle_expired_auctions


class Command(BaseCommand):
    help = "Encerra e liquida todos os lotes vencidos."

    def handle(self, *args, **options):
        count = settle_expired_auctions()
        self.stdout.write(self.style.SUCCESS(f"{count} lote(s) liquidado(s)"))
