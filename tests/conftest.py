import django
from django.conf import settings

if not settings.configured:
    settings.configure(
        INSTALLED_APPS=["django.contrib.staticfiles", "pay_client", "appli_test"],
        ROOT_URLCONF="urls_test",
        CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
        PAY_URL="http://pay.test",
        PAY_API_KEY="ck_test_essai",
        PAY_WEBHOOK_SECRET="whsec_essai",
        ALLOWED_HOSTS=["*"],
        USE_TZ=True,
        PAY_COMMANDE="appli_test.commandes.commande_a_payer",
        STATIC_URL="/static/",
        TEMPLATES=[
            {"BACKEND": "django.template.backends.django.DjangoTemplates", "APP_DIRS": True}
        ],
    )
    django.setup()
