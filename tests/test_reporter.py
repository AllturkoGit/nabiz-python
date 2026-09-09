import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_hub import FakeHub  # noqa: E402

from nabiz.reporter import KINDS, Reporter  # noqa: E402

SECRET = "s" * 64


def reporter_for(hub, **options):
    settings = {"url": hub.url, "key": "proje", "secret": SECRET, "timeout": 2.0}
    settings.update(options)

    return Reporter(**settings)


class ReporterTest(unittest.TestCase):
    def test_istisna_hubun_kabul_ettigi_bicimde_gider(self):
        with FakeHub(SECRET) as hub:
            reporter = reporter_for(hub)

            try:
                raise ValueError("ürün bulunamadı")
            except ValueError as error:
                reporter.record_exception(error, route="/urun/<id>", method="GET", block=True)

        body = hub.requests[0]["body"]
        self.assertTrue(hub.requests[0]["accepted"])
        self.assertIn(body["kind"], KINDS)
        self.assertEqual("exception", body["kind"])
        self.assertEqual("ürün bulunamadı", body["msg"])
        self.assertEqual("ValueError", body["exception_class"])
        self.assertEqual("production", body["env"])
        self.assertEqual("server", body["source"])
        self.assertEqual("python", body["runtime"])
        self.assertIn("traceback", body["stack"].lower())

    def test_ayni_istisna_iki_kez_gitmez(self):
        with FakeHub(SECRET) as hub:
            reporter = reporter_for(hub)
            error = ValueError("x")

            reporter.record_exception(error, block=True)
            result = reporter.record_exception(error, block=True)

        self.assertEqual("zaten-raporlandi", result["error"])
        self.assertEqual(1, len(hub.requests))

    def test_bellek_hatasi_fatal_olarak_isaretlenir(self):
        with FakeHub(SECRET) as hub:
            reporter_for(hub).record_exception(MemoryError("bellek bitti"), block=True)

        self.assertEqual("fatal", hub.requests[0]["body"]["kind"])

    def test_mesajdaki_kisisel_veri_temizlenir(self):
        with FakeHub(SECRET) as hub:
            reporter_for(hub).record_exception(
                ValueError("ahmet@ornek.com için kayıt yok"), block=True
            )

        self.assertNotIn("ahmet@ornek.com", hub.requests[0]["raw"].decode("utf-8"))

    def test_hizli_ve_basarili_istek_raporlanmaz(self):
        with FakeHub(SECRET) as hub:
            reporter_for(hub).record_request("/", "GET", 200, 10, block=True)

        self.assertEqual([], hub.requests)

    def test_yavas_istek_raporlanir(self):
        with FakeHub(SECRET) as hub:
            reporter_for(hub, slow_request_ms=100).record_request("/ara", "GET", 200, 250, block=True)

        body = hub.requests[0]["body"]
        self.assertEqual("slow_request", body["kind"])
        self.assertEqual(250, body["duration_ms"])
        self.assertEqual("GET /ara", body["route"])

    def test_sunucu_hatasi_5xx_olarak_raporlanir(self):
        with FakeHub(SECRET) as hub:
            reporter_for(hub).record_request("/api/analiz", "POST", 500, 20, block=True)

        self.assertEqual("http_5xx", hub.requests[0]["body"]["kind"])

    def test_canlilik_istegi_olay_tasimaz(self):
        with FakeHub(SECRET) as hub:
            reporter_for(hub).heartbeat()

        body = hub.requests[0]["body"]
        self.assertEqual([], body["events"])
        self.assertNotIn("kind", body)
        self.assertEqual("python", body["runtime"])

    def test_kuyruk_kullanildiginda_cagri_beklemez(self):
        with FakeHub(SECRET) as hub:
            reporter = reporter_for(hub)
            result = reporter.record_exception(ValueError("kuyruk"))

            self.assertTrue(result["queued"])
            self.assertTrue(reporter.flush(5), "kuyruk boşalmalı")

        self.assertEqual(1, len(hub.requests))

    def test_kuyruk_dolarsa_olay_dusurulur_uygulama_beklemez(self):
        # Erişilemeyen hub: gönderim thread'i takılır, kuyruk dolar. Beklenen
        # davranış olayı düşürmek — bloke olmak izlenen uygulamayı yavaşlatır.
        reporter = Reporter(url="http://127.0.0.1:9", key="k", secret=SECRET, timeout=5)
        results = [reporter.record_exception(ValueError(f"hata {i}")) for i in range(400)]

        self.assertTrue(any(r.get("error") == "kuyruk-dolu" for r in results))

    def test_yapilandirma_yoksa_sessizce_vazgecilir(self):
        result = Reporter(url=None, key=None, secret=None).record_exception(ValueError("x"))

        self.assertEqual("yapilandirma-eksik", result["error"])

    def test_devre_disiyken_hicbir_sey_gonderilmez(self):
        with FakeHub(SECRET) as hub:
            reporter_for(hub, enabled=False).record_exception(ValueError("x"), block=True)

        self.assertEqual([], hub.requests)

    def test_gecersiz_ortam_productiona_dusurulur(self):
        # Hub küme dışı env'i sessizce atar; SDK bunu hiç göndermemeli.
        self.assertEqual("production", Reporter(env="prod").env)
        self.assertEqual("staging", Reporter(env="staging").env)


if __name__ == "__main__":
    unittest.main()
