from django.urls import include, path

from audit.views import AuctionAuditView

urlpatterns = [
    path("<int:auction_id>/bids/", include("bidding.urls")),
    path(
        "<int:auction_id>/audit/",
        AuctionAuditView.as_view(),
        name="auction-audit",
    ),
]
