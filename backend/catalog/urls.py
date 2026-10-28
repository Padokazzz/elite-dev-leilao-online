from django.urls import path

from .views import ArtworkImportView, ArtworkImageView, ArtworkSearchView

urlpatterns = [
    path("search/", ArtworkSearchView.as_view(), name="artwork-search"),
    path("import/", ArtworkImportView.as_view(), name="artwork-import"),
    path(
        "image/<int:item_id>/",
        ArtworkImageView.as_view(),
        name="artwork-image",
    ),
]
