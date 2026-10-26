from django.urls import path

from .views import ReceiptDetailView

urlpatterns = [
    path(
        "<uuid:public_uuid>/",
        ReceiptDetailView.as_view(),
        name="receipt-detail",
    ),
]
