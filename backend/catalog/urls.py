from django.urls import path

from .views import ArtworkImportView, ArtworkSearchView


urlpatterns = [
    path("search/", ArtworkSearchView.as_view(), name="artwork-search"),
    path("import/", ArtworkImportView.as_view(), name="artwork-import"),
]
