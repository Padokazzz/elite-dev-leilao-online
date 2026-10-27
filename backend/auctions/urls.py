from django.urls import include, path

from audit.views import AuctionAuditView

from . import views

urlpatterns = [
    path("", views.AuctionListCreateView.as_view(), name="auction-list"),
    path("<int:auction_id>/bids/", include("bidding.urls")),
    path(
        "<int:auction_id>/audit/",
        AuctionAuditView.as_view(),
        name="auction-audit",
    ),
    path(
        "<int:auction_id>/cancel/",
        views.AuctionCancelView.as_view(),
        name="auction-cancel",
    ),
    path(
        "<int:auction_id>/",
        views.AuctionManageView.as_view(),
        name="auction-manage",
    ),
]
