import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import django
    from django.conf import settings
except ImportError:  # pragma: no cover
    django = None

from fake_hub import FakeHub  # noqa: E402

SECRET = "s" * 64

urlpatterns = []

if django is not None:
    from django.core.exceptions import PermissionDenied
    from django.http import Http404, HttpResponse
    from django.urls import path, re_path

    def urun(request, urun_id):
        return HttpResponse(str(urun_id))

    def urun_patlat(request, urun_id):
        raise RuntimeError("kasıtlı hata")

    def bakim(request):
        return HttpResponse("bakımda", status=503)

    def yasak(request):
        raise PermissionDenied()

    def bulunamadi(request):
        raise Http404()

    def eski(request, kod):
        raise ValueError("eski rota")

    urlpatterns = [
        path("urun/<int:urun_id>/", urun),
        path("urun/<int:urun_id>/patlat/", urun_patlat),
        path("bakim/", bakim),
        path("yasak/", yasak),
        path("bulunamadi/", bulunamadi),
        path("ara-katman/", urun, {"urun_id": 1}),
        re_path(r"^eski/(?P<kod>\d+)/$", eski),
    ]

    class ExplodingMiddleware:
        """Bizim altımızda patlayan ara katman: process_exception onu görmez."""

        def __init__(self, get_response):
            self.get_response = get_response

        def __call__(self, request):
            if request.path == "/ara-katman/":
                raise RuntimeError("ara katman hatası")

            return self.get_response(request)

    if not settings.configured:
        settings.configure(
            DEBUG=False,
            SECRET_KEY="test",
            ALLOWED_HOSTS=["testserver"],
            ROOT_URLCONF=__name__,
            INSTALLED_APPS=[],
            DATABASES={},
            TEMPLATES=[],
            MIDDLEWARE=[
                "nabiz.django.NabizMiddleware",
                f"{__name__}.ExplodingMiddleware",
            ],
            # Test sürecinin excepthook'u değişmesin.
            NABIZ_HOOK_PROCESS=False,
            # Django 500'leri stderr'e basmasın.
            LOGGING={
                "version": 1,
                "disable_existing_loggers": False,
                "loggers": {"django": {"handlers": [], "level": "CRITICAL", "propagate": False}},
            },
        )
        django.setup()


@unittest.skipIf(django is None, "django kurulu değil")
class DjangoTest(unittest.TestCase):
    def setUp(self):
        import nabiz

        self.hub = FakeHub(SECRET).__enter__()
        self.addCleanup(self.hub.__exit__, None, None, None)

        nabiz._instance = None
        self.reporter = nabiz.init(
            url=self.hub.url, key="proje", secret=SECRET, slow_request_ms=100, timeout=2.0
        )

    def client(self):
        from django.test import Client

        # Test istemcisi sunucu hatasını varsayılan olarak yeniden fırlatır;
        # gerçek sunucudaki gibi 500 sayfası görülsün.
        return Client(raise_request_exception=False)

    def events(self):
        self.reporter.flush(5)

        return [request["body"] for request in self.hub.requests]

    def test_basarili_istek_raporlanmaz(self):
        response = self.client().get("/urun/7/")

        self.assertEqual(200, response.status_code)
        self.assertEqual([], self.events())

    def test_gonderilmeyecek_istekte_rota_deseni_hesaplanmaz(self):
        from unittest import mock

        import nabiz.django

        with mock.patch.object(nabiz.django, "route_pattern", wraps=nabiz.django.route_pattern) as spy:
            self.client().get("/urun/7/")
            self.assertEqual(0, spy.call_count)

            self.client().get("/bakim/")
            self.assertEqual(1, spy.call_count)

    def test_yakalanmamis_istisna_tek_kayit_ve_rota_deseniyle_raporlanir(self):
        response = self.client().get("/urun/42/patlat/")

        # Uygulamanın kendi davranışı korunur: hata yutulmaz, 500 sayfası döner.
        self.assertEqual(500, response.status_code)

        events = self.events()
        self.assertEqual(["exception"], [event["kind"] for event in events])
        self.assertEqual("RuntimeError", events[0]["exception_class"])
        self.assertEqual("kasıtlı hata", events[0]["msg"])
        # Gerçek id değil, desen.
        self.assertEqual("/urun/<int:urun_id>/patlat/", events[0]["route"])
        self.assertEqual("GET", events[0]["method"])
        self.assertIn("urun_patlat", events[0]["stack"])
        self.assertTrue(all(r["accepted"] for r in self.hub.requests))

    def test_istisna_test_istemcisinde_yeniden_firlatilir(self):
        # Hata yutulmuyor: Django'nun kendi zinciri (sinyal → istemci) çalışıyor.
        from django.test import Client

        with self.assertRaises(RuntimeError):
            Client().get("/urun/1/patlat/")

    def test_alt_ara_katman_hatasi_da_stackle_raporlanir(self):
        response = self.client().get("/ara-katman/")

        self.assertEqual(500, response.status_code)

        events = self.events()
        self.assertEqual(["exception"], [event["kind"] for event in events])
        self.assertEqual("ara katman hatası", events[0]["msg"])

    def test_hatasiz_5xx_http_5xx_olarak_raporlanir(self):
        response = self.client().get("/bakim/")

        self.assertEqual(503, response.status_code)

        events = self.events()
        self.assertEqual(["http_5xx"], [event["kind"] for event in events])
        self.assertEqual("GET /bakim/", events[0]["route"])
        self.assertEqual(503, events[0]["status"])

    def test_4xx_gonderilmez(self):
        client = self.client()

        self.assertEqual(403, client.get("/yasak/").status_code)
        self.assertEqual(404, client.get("/bulunamadi/").status_code)
        self.assertEqual(404, client.get("/hic-yok/?token=gizli").status_code)

        self.assertEqual([], self.events())

    def test_process_exception_hatayi_yutmaz_ve_4xx_not_etmez(self):
        from django.http import Http404
        from django.test import RequestFactory

        from nabiz.django import NabizMiddleware

        middleware = NabizMiddleware(lambda request: None)
        request = RequestFactory().get("/")

        self.assertIsNone(middleware.process_exception(request, Http404()))
        self.assertFalse(hasattr(request, "_nabiz_exception"))

        error = RuntimeError("x")
        self.assertIsNone(middleware.process_exception(request, error))
        self.assertIs(error, request._nabiz_exception)

    def test_sinyal_kacarsa_not_edilen_istisna_raporlanir(self):
        # got_request_exception bir şekilde tetiklenmezse process_exception'ın
        # notu istek sonunda, yanıt 5xx ise, tek kayıt olarak gönderilir.
        from django.http import HttpResponse
        from django.test import RequestFactory

        from nabiz.django import NabizMiddleware

        def view(request):
            middleware.process_exception(request, RuntimeError("notlu"))

            return HttpResponse(status=500)

        middleware = NabizMiddleware(view)
        middleware(RequestFactory().get("/x"))

        events = self.events()
        self.assertEqual(["exception"], [event["kind"] for event in events])
        self.assertEqual("notlu", events[0]["msg"])

    def test_re_path_deseni_temizlenir(self):
        response = self.client().get("/eski/123/")

        self.assertEqual(500, response.status_code)

        events = self.events()
        self.assertEqual(["exception"], [event["kind"] for event in events])
        self.assertEqual("/eski/(?P<kod>\\d+)/", events[0]["route"])

    def test_sonradan_init_edilen_raporlayici_kullanilir(self):
        import nabiz

        client = self.client()
        yeni = nabiz.init(url=self.hub.url, key="yeni-proje", secret=SECRET, timeout=2.0)

        client.get("/urun/1/patlat/")
        yeni.flush(5)

        self.assertTrue(self.hub.requests)
        self.assertTrue(all("/yeni-proje/" in r["path"] for r in self.hub.requests))

    def test_eslesmeyen_yol_query_stringsiz_dusulur(self):
        from django.test import RequestFactory

        from nabiz.django import route_pattern

        self.assertEqual("/yok", route_pattern(RequestFactory().get("/yok?token=gizli")))


if __name__ == "__main__":
    unittest.main()
