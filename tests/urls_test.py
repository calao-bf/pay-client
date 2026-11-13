from django.urls import include, path

urlpatterns = [path("pay/", include("pay_client.urls"))]
