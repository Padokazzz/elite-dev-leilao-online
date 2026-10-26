from django.urls import path

from .views import AuctionBidsView

urlpatterns = [
    path("", AuctionBidsView.as_view(), name="auction-bids"),
]