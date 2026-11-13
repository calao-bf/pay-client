from django.urls import include, path

from pay_client.vues import webhook

urlpatterns = [path("pay/", include("pay_client.urls")), path("notifications", webhook)]
