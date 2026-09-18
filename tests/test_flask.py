import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from flask import Flask
except ImportError:  # pragma: no cover
    Flask = None

from fake_hub import FakeHub  # noqa: E402

SECRET = "s" * 64


@unittest.skipIf(Flask is None, "flask kurulu değil")
class FlaskTest(unittest.TestCase):
    def setUp(self):
        import nabiz

        self.hub = FakeHub(SECRET).__enter__()
        self.addCleanup(self.hub.__exit__, None, None, None)

        # Her test kendi raporlayıcısını kurar; modül düzeyindeki tekil
        # örnek testler arasında sızmasın.
        nabiz._instance = None
        self.reporter = nabiz.init(
            url=self.hub.url, key="proje", secret=SECRET, slow_request_ms=100, timeout=2.0
        )

    def app(self):
        from nabiz.flask import NabizFlask

        app = Flask(__name__)
        app.config["PROPAGATE_EXCEPTIONS"] = False

        @app.route("/urun/<int:urun_id>")
        def urun(urun_id):
            return {"id": urun_id}

        @app.route("/patlat")
        def patlat():
            raise RuntimeError("kasıtlı hata")

        # hook_process_errors kapalı: test sürecinin excepthook'unu değiştirmesin.
        NabizFlask(app, hook_process_errors=False)

        return app

    def test_basarili_istek_raporlanmaz(self):
        self.app().test_client().get("/urun/7")
        self.reporter.flush(3)

        self.assertEqual([], self.hub.requests)

    def test_yakalanmamis_istisna_rota_deseniyle_raporlanir(self):
        response = self.app().test_client().get("/patlat")
        self.reporter.flush(5)

        # Uygulamanın kendi davranışı korunur: hata yutulmaz, 500 döner.
        self.assertEqual(500, response.status_code)

        kinds = {request["body"]["kind"] for request in self.hub.requests}
        self.assertIn("exception", kinds)

        event = next(r["body"] for r in self.hub.requests if r["body"]["kind"] == "exception")
        self.assertEqual("kasıtlı hata", event["msg"])
        self.assertEqual("RuntimeError", event["exception_class"])
        self.assertEqual("/patlat", event["route"])
        self.assertTrue(all(r["accepted"] for r in self.hub.requests))

    def test_hata_veren_istek_tek_kayit_acar(self):
        # Eskiden stack'li exception + stack'siz http_5xx: tek arıza iki kayıt.
        self.app().test_client().get("/patlat")
        self.reporter.flush(5)

        kinds = [request["body"]["kind"] for request in self.hub.requests]
        self.assertEqual(["exception"], kinds)

    def test_hatasiz_5xx_http_5xx_olarak_raporlanir(self):
        app = self.app()

        @app.route("/bakim")
        def bakim():
            return "bakımda", 503

        app.test_client().get("/bakim")
        self.reporter.flush(5)

        kinds = [request["body"]["kind"] for request in self.hub.requests]
        self.assertEqual(["http_5xx"], kinds)

    def test_errorhandler_exception_varken_hata_kaybolmaz(self):
        # Uygulama Exception için işleyici tanımlayınca teardown error=None
        # alıyordu; yalnızca stack'siz http_5xx gidiyor, hata kayboluyordu.
        app = self.app()

        @app.errorhandler(Exception)
        def hepsi(e):
            return "özür dileriz", 500

        response = app.test_client().get("/patlat")
        self.reporter.flush(5)

        self.assertEqual(500, response.status_code)
        kinds = [request["body"]["kind"] for request in self.hub.requests]
        self.assertEqual(["exception"], kinds)
        self.assertEqual("RuntimeError", self.hub.requests[0]["body"]["exception_class"])

    def test_errorhandler_4xx_donerse_gonderilmez(self):
        app = self.app()

        @app.errorhandler(RuntimeError)
        def istemci(e):
            return "geçersiz", 400

        app.test_client().get("/patlat")
        self.reporter.flush(3)

        self.assertEqual([], self.hub.requests)

    def test_abort_4xx_gonderilmez(self):
        app = self.app()

        @app.route("/yasak")
        def yasak():
            from flask import abort

            abort(403)

        app.test_client().get("/yasak")
        app.test_client().get("/hic-yok")
        self.reporter.flush(3)

        self.assertEqual([], self.hub.requests)

    def test_iki_kez_kurulum_cift_kayit_acmaz(self):
        # after_request iki kez kaydediliyor, yavaş istek iki olay açıyordu.
        import time as _time

        from nabiz.flask import NabizFlask

        app = self.app()
        NabizFlask(app, hook_process_errors=False)

        @app.route("/yavas")
        def yavas():
            _time.sleep(0.15)
            return "tamam"

        @app.route("/kapat")
        def kapat():
            from flask import abort

            abort(500)

        client = app.test_client()
        client.get("/yavas")
        client.get("/kapat")
        self.reporter.flush(5)

        kinds = sorted(request["body"]["kind"] for request in self.hub.requests)
        self.assertEqual(["http_5xx", "slow_request"], kinds)

    def test_isleyici_metin_durum_500_donerse_stackle_raporlanir(self):
        app = self.app()

        @app.errorhandler(RuntimeError)
        def metin(e):
            return "özür", "500 SUNUCU HATASI"

        response = app.test_client().get("/patlat")
        self.reporter.flush(5)

        self.assertEqual(500, response.status_code)
        kinds = [request["body"]["kind"] for request in self.hub.requests]
        self.assertEqual(["exception"], kinds)

    def test_kurulum_hatasi_uygulamayi_dusurmez(self):
        from unittest import mock

        from nabiz.flask import NabizFlask

        app = Flask(__name__)

        with mock.patch.object(NabizFlask, "_install", side_effect=RuntimeError("bozuk")):
            self.assertIs(app, NabizFlask(hook_process_errors=False).init_app(app))

    def test_server_error_durum_bicimleri(self):
        from nabiz.flask import _server_error

        self.assertTrue(_server_error(("x", 500)))
        self.assertTrue(_server_error(("x", "503 BAKIM")))
        self.assertTrue(_server_error(("x", "500", {"X": "1"})))
        self.assertFalse(_server_error(("x", "404 YOK")))
        self.assertFalse(_server_error(("x", {"X": "1"})))
        self.assertFalse(_server_error(("x", "bozuk")))
        self.assertFalse(_server_error("düz gövde"))

    def test_sonradan_init_edilen_raporlayici_kullanilir(self):
        # Kancalar raporlayıcıyı kurulumda yakalıyordu; sonraki init'i görmüyordu.
        import nabiz

        app = self.app()
        yeni = nabiz.init(url=self.hub.url, key="yeni-proje", secret=SECRET, timeout=2.0)

        app.test_client().get("/patlat")
        yeni.flush(5)

        self.assertTrue(self.hub.requests)
        self.assertTrue(all("/yeni-proje/" in r["path"] for r in self.hub.requests))

    def test_rota_deseni_gonderilir_gercek_id_degil(self):
        from nabiz.flask import route_pattern

        app = self.app()

        with app.test_request_context("/urun/42"):
            from flask import request

            self.assertEqual("/urun/<int:urun_id>", route_pattern(request))

    def test_eslesmeyen_yol_query_stringsiz_dusulur(self):
        from nabiz.flask import route_pattern

        app = self.app()

        with app.test_request_context("/yok?token=gizli"):
            from flask import request

            self.assertEqual("/yok", route_pattern(request))


if __name__ == "__main__":
    unittest.main()
