from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from bidding.services import place_bid
from catalog.models import AuctionItem
from catalog.services import ArtworkAPIError, search_artworks
from wallets.services import deposit, get_or_create_wallet

from auctions.models import Auction
from auctions.services import cancel_auction, settle_auction

User = get_user_model()

DEMO_PASSWORD = "demo12345"

FALLBACK_ITEMS = (
    {
        "title": "Retrato de uma dama desconhecida",
        "description": "Óleo sobre tela, escola flamenga, séc. XVII.",
        "image_url": "",
        "attributes": {
            "artist": "Escola flamenga (autor desconhecido)",
            "date": "séc. XVII",
            "medium": "Óleo sobre tela",
            "dimensions": "62 × 48 cm",
            "is_public_domain": True,
        },
    },
    {
        "title": "Natureza-morta com frutas",
        "description": "Pintura flamenga, séc. XVII.",
        "image_url": "",
        "attributes": {
            "artist": "Escola flamenga (autor desconhecido)",
            "date": "séc. XVII",
            "medium": "Óleo sobre painel de madeira",
            "dimensions": "54 × 71 cm",
            "is_public_domain": True,
        },
    },
    {
        "title": "Marina ao pôr do sol",
        "description": "Óleo sobre tela, tradição holandesa.",
        "image_url": "",
        "attributes": {
            "artist": "Escola holandesa (autor desconhecido)",
            "date": "séc. XVII",
            "medium": "Óleo sobre tela",
            "dimensions": "48 × 66 cm",
            "is_public_domain": True,
        },
    },
    {
        "title": "Estudo de figuras",
        "description": "Desenho a nanquim sobre papel.",
        "image_url": "",
        "attributes": {
            "artist": "Autor desconhecido",
            "date": "séc. XIX",
            "medium": "Nanquim sobre papel",
            "dimensions": "31 × 24 cm",
            "is_public_domain": True,
        },
    },
)


class Command(BaseCommand):
    help = "Popula o banco com dados de demonstração (idempotente)."

    def handle(self, *args, **options):
        seller = self._user(
            "leiloeiro@demo.com", "leiloeiro", User.Role.AUCTIONEER
        )
        licitante1 = self._user(
            "licitante1@demo.com", "licitante1", User.Role.BIDDER
        )
        licitante2 = self._user(
            "licitante2@demo.com", "licitante2", User.Role.BIDDER
        )

        self._fund(licitante1, 500_000)
        self._fund(licitante2, 500_000)

        items = self._items()

        live = self._auction(
            items[0],
            seller,
            starts_in=timedelta(minutes=-30),
            ends_in=timedelta(minutes=10),
            status=Auction.Status.LIVE,
        )
        scheduled = self._auction(
            items[1],
            seller,
            starts_in=timedelta(minutes=5),
            ends_in=timedelta(hours=2),
            status=Auction.Status.SCHEDULED,
        )
        ended = self._auction(
            items[2],
            seller,
            starts_in=timedelta(hours=-3),
            ends_in=timedelta(minutes=30),
            status=Auction.Status.LIVE,
        )
        cancelled = self._auction(
            items[3],
            seller,
            starts_in=timedelta(hours=-3),
            ends_in=timedelta(hours=1),
            status=Auction.Status.LIVE,
        )

        self._rearm(live, scheduled)
        self._play(live, [(licitante1, 10_000), (licitante2, 11_000)])
        self._finish(
            ended,
            [
                (licitante1, 10_000),
                (licitante2, 11_000),
                (licitante1, 12_000),
            ],
        )
        self._cancel(cancelled)

        self._report([
            ("AO VIVO", live),
            ("AGENDADO", scheduled),
            ("ENCERRADO", ended),
            ("CANCELADO", cancelled),
        ])

    def _user(self, email, username, role):
        user, _ = User.objects.get_or_create(
            email=email,
            defaults={"username": username, "role": role},
        )

        if user.role != role:
            user.role = role
            user.save(update_fields=["role"])

        if not user.check_password(DEMO_PASSWORD):
            user.set_password(DEMO_PASSWORD)
            user.save(update_fields=["password"])

        return user

    def _fund(self, user, cents):
        wallet = get_or_create_wallet(user)
        if wallet.balance_cents == 0:
            deposit(wallet_id=wallet.pk, amount_cents=cents)

    def _items(self):
        artworks = None
        try:
            artworks = search_artworks("painting", limit=4)
        except (ArtworkAPIError, ValueError):
            artworks = None

        if artworks is not None and len(artworks) < 4:
            artworks = None

        items = []
        for index, fallback in enumerate(FALLBACK_ITEMS, start=1):
            content = dict(fallback)
            if artworks:
                artwork = artworks[index - 1]
                content = {
                    "title": artwork["title"],
                    "description": artwork["description"],
                    "image_url": artwork["image_url"],
                    "attributes": artwork["attributes"],
                }

            item, created = AuctionItem.objects.get_or_create(
                source="demo",
                external_id=f"demo-{index}",
                defaults=content,
            )
            if not created:
                # Retrofita dados de seeds antigos: ficha vazia ganha
                # attributes; descrição com HTML cru (rodadas antigas
                # gravavam o retorno do museu sem normalizar) é trocada
                # pela versão em texto puro.
                updates = {}
                if content.get("attributes") and not item.attributes:
                    updates["attributes"] = content["attributes"]
                stored_description = item.description or ""
                if (
                    "<" in stored_description
                    and ">" in stored_description
                    and content.get("description")
                ):
                    updates["description"] = content["description"]
                if updates:
                    for field, value in updates.items():
                        setattr(item, field, value)
                    item.save(update_fields=list(updates))
            items.append(item)

        return items

    def _auction(self, item, seller, *, starts_in, ends_in, status):
        now = timezone.now()
        auction, _ = Auction.objects.get_or_create(
            item=item,
            seller=seller,
            defaults={
                "starting_bid_cents": 10_000,
                "minimum_increment_cents": 500,
                "starts_at": now + starts_in,
                "ends_at": now + ends_in,
                "status": status,
            },
        )
        return auction

    def _rearm(self, live, scheduled):
        now = timezone.now()

        if live.status == Auction.Status.LIVE and (
            live.ends_at < now + timedelta(minutes=10)
        ):
            Auction.objects.filter(pk=live.pk).update(
                ends_at=now + timedelta(minutes=10)
            )

        if scheduled.status == Auction.Status.SCHEDULED:
            Auction.objects.filter(pk=scheduled.pk).update(
                starts_at=now + timedelta(minutes=5),
                ends_at=now + timedelta(hours=2),
            )

    def _play(self, auction, bids):
        if auction.bids.exists():
            return

        for bidder, amount in bids:
            place_bid(
                auction_id=auction.pk,
                bidder=bidder,
                amount_cents=amount,
            )

    def _finish(self, auction, bids):
        if auction.status == Auction.Status.ENDED:
            return

        if not auction.bids.exists():
            for bidder, amount in bids:
                place_bid(
                    auction_id=auction.pk,
                    bidder=bidder,
                    amount_cents=amount,
                )

        Auction.objects.filter(pk=auction.pk).update(
            ends_at=timezone.now() - timedelta(hours=1)
        )
        settle_auction(auction.pk)

    def _cancel(self, auction):
        if auction.status == Auction.Status.CANCELLED:
            return

        cancel_auction(auction_id=auction.pk, seller=auction.seller)

    def _report(self, lots):
        for label, auction in lots:
            auction.refresh_from_db()

        self.stdout.write(self.style.SUCCESS("Seed concluído."))
        self.stdout.write("  leiloeiro@demo.com  / demo12345")
        self.stdout.write("  licitante1@demo.com / demo12345")
        self.stdout.write("  licitante2@demo.com / demo12345")

        for label, auction in lots:
            self.stdout.write(
                f"  lote {auction.pk}: {label} — {auction.item.title}"
            )
