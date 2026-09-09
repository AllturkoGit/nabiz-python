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

    def test_500_ayrica_http_5xx_olarak_raporlanir(self):
        self.app().test_client().get("/patlat")
        self.reporter.flush(5)

        kinds = {request["body"]["kind"] for request in self.hub.requests}
        self.assertIn("http_5xx", kinds)

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
