from django.urls import path

from . import views


urlpatterns = [
    path("", views.index, name="galeria"),
    path("api/upload/", views.upload_foto, name="upload_foto"),
]
