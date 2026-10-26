from django.urls import include, path

urlpatterns = [
    path("<int:auction_id>/bids/", include("bidding.urls")),
]