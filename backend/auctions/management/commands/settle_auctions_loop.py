import signal
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from auctions.services import settle_expired_auctions


class Command(BaseCommand):
    help = "Worker: roda a liquidação em loop."

    def add_arguments(self, parser):
        parser.add_argument("--interval", type=float, default=5.0)

    def handle(self, *args, **options):
        interval = options["interval"]
        stopping = False

        def stop(signum, frame):
            nonlocal stopping
            stopping = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)

        self.stdout.write(f"worker de liquidação ativo ({interval}s)")

        while not stopping:
            close_old_connections()
            try:
                count = settle_expired_auctions()
            except Exception as exc:
                self.stderr.write(f"falha na rodada de liquidação: {exc!r}")
            else:
                if count:
                    self.stdout.write(f"{count} lote(s) liquidado(s)")
            time.sleep(interval)

        self.stdout.write("worker encerrado")
