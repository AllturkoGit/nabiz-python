import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import JSONResponse, PlainTextResponse
    from starlette.testclient import TestClient
except ImportError:  # pragma: no cover
    FastAPI = None

from fake_hub import FakeHub  # noqa: E402

SECRET = "s" * 64


class _Base(unittest.TestCase):
    def setUp(self):
        import nabiz

        self.hub = FakeHub(SECRET).__enter__()
        self.addCleanup(self.hub.__exit__, None, None, None)

        nabiz._instance = None
        self.reporter = nabiz.init(
            url=self.hub.url, key="proje", secret=SECRET, slow_request_ms=100, timeout=2.0
        )

    def events(self):
        self.reporter.flush(5)

        return [request["body"] for request in self.hub.requests]

    def kinds(self):
        return [event["kind"] for event in self.events()]


class RawAsgiTest(_Base):
    """Çerçevesiz ASGI: Starlette/FastAPI kurulu olmasa da çalışmalı."""

    def run_app(self, app, path="/ham", scope_type="http"):
        from nabiz.asgi import NabizASGIMiddleware

        wrapped = NabizASGIMiddleware(app, hook_process_errors=False)
        sent = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent.append(message)

        scope = {"type": scope_type, "method": "GET", "path": path, "root_path": ""}
        asyncio.run(wrapped(scope, receive, send))

        return sent

    def test_istisna_yeniden_firlatilir_ve_tek_kayit_acar(self):
        async def app(scope, receive, send):
            raise RuntimeError("ham hata")

        with self.assertRaises(RuntimeError):
            self.run_app(app, path="/ham?token=gizli")

        events = self.events()
        self.assertEqual(["exception"], [event["kind"] for event in events])
        self.assertEqual("/ham", events[0]["route"])
        self.assertEqual("GET", events[0]["method"])

    def test_yanit_basladiktan_sonra_istisna_http_5xx_acmaz(self):
        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 500, "headers": []})
            raise RuntimeError("yarıda")

        with self.assertRaises(RuntimeError):
            self.run_app(app)

        self.assertEqual(["exception"], self.kinds())

    def test_hatasiz_5xx_raporlanir_yanit_degismez(self):
        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 502, "headers": []})
            await send({"type": "http.response.body", "body": b"x"})

        sent = self.run_app(app)

        self.assertEqual(502, sent[0]["status"])
        self.assertEqual(b"x", sent[1]["body"])
        self.assertEqual(["http_5xx"], self.kinds())

    def test_4xx_http_exception_gonderilmez(self):
        class HTTPException(Exception):
            def __init__(self, status_code):
                self.status_code = status_code

        async def app(scope, receive, send):
            raise HTTPException(404)

        with self.assertRaises(HTTPException):
            self.run_app(app)

        self.assertEqual([], self.events())

    def test_istemci_hatasi_denetimi_patlarsa_ozgun_hata_firlatilir(self):
        class Tuhaf(Exception):
            @property
            def status_code(self):
                raise KeyError("özellik patladı")

        async def app(scope, receive, send):
            raise Tuhaf("özgün")

        with self.assertRaises(Tuhaf):
            self.run_app(app)

    def test_ic_ice_katman_tek_kayit(self):
        from nabiz.asgi import NabizASGIMiddleware

        async def app(scope, receive, send):
            await asyncio.sleep(0.15)
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"x"})

        inner = NabizASGIMiddleware(app, hook_process_errors=False)
        self.run_app(inner, path="/ic")

        self.assertEqual(["slow_request"], self.kinds())

    def test_http_disi_scope_olculmez(self):
        async def app(scope, receive, send):
            raise RuntimeError("lifespan")

        with self.assertRaises(RuntimeError):
            self.run_app(app, scope_type="lifespan")

        self.assertEqual([], self.events())


@unittest.skipIf(FastAPI is None, "fastapi/starlette kurulu değil")
class FastAPITest(_Base):
    def app(self):
        from nabiz.asgi import NabizASGIMiddleware

        app = FastAPI()

        @app.get("/urun/{urun_id}")
        def urun(urun_id: int):
            return {"id": urun_id}

        @app.get("/urun/{urun_id}/patlat")
        def urun_patlat(urun_id: int):
            raise RuntimeError("kasıtlı hata")

        @app.get("/patlat-async")
        async def patlat_async():
            raise RuntimeError("async hata")

        @app.get("/bakim")
        def bakim():
            return JSONResponse({"durum": "bakım"}, status_code=503)

        @app.get("/yasak")
        def yasak():
            raise HTTPException(status_code=403)

        @app.get("/bulunamadi")
        def bulunamadi():
            raise HTTPException(status_code=404)

        @app.get("/deger")
        def deger():
            raise ValueError("geçersiz değer")

        app.add_middleware(NabizASGIMiddleware, hook_process_errors=False)

        return app

    def client(self, app, raise_server_exceptions=False):
        return TestClient(app, raise_server_exceptions=raise_server_exceptions)

    def test_basarili_istek_raporlanmaz(self):
        response = self.client(self.app()).get("/urun/7")

        self.assertEqual(200, response.status_code)
        self.assertEqual([], self.events())

    def test_yakalanmamis_istisna_tek_kayit_ve_rota_deseniyle_raporlanir(self):
        response = self.client(self.app()).get("/urun/42/patlat")

        self.assertEqual(500, response.status_code)

        events = self.events()
        self.assertEqual(["exception"], [event["kind"] for event in events])
        self.assertEqual("RuntimeError", events[0]["exception_class"])
        self.assertEqual("/urun/{urun_id}/patlat", events[0]["route"])
        self.assertEqual("GET", events[0]["method"])
        self.assertTrue(all(r["accepted"] for r in self.hub.requests))

    def test_async_uc_nokta_istisnasi_raporlanir(self):
        self.client(self.app()).get("/patlat-async")

        self.assertEqual(["exception"], self.kinds())

    def test_istisna_yutulmaz(self):
        # ServerErrorMiddleware 500'ü yazıp hatayı yeniden fırlatıyor; bizim
        # katmanımız araya girdiğinde de hata dışarı ulaşmalı.
        with self.assertRaises(RuntimeError):
            self.client(self.app(), raise_server_exceptions=True).get("/urun/1/patlat")

    def test_hatasiz_5xx_http_5xx_olarak_raporlanir(self):
        response = self.client(self.app()).get("/bakim")

        self.assertEqual(503, response.status_code)

        events = self.events()
        self.assertEqual(["http_5xx"], [event["kind"] for event in events])
        self.assertEqual("GET /bakim", events[0]["route"])

    def test_4xx_gonderilmez(self):
        client = self.client(self.app())

        self.assertEqual(403, client.get("/yasak").status_code)
        self.assertEqual(404, client.get("/bulunamadi").status_code)
        self.assertEqual(404, client.get("/hic-yok?token=gizli").status_code)
        self.assertEqual(422, client.get("/urun/abc").status_code)

        self.assertEqual([], self.events())

    def test_http_exception_5xx_stacksiz_http_5xx_acar(self):
        # Bilinçli HTTPException(503) arıza stack'i değil; Flask'taki abort(503)
        # gibi yalnızca http_5xx olarak düşer.
        app = self.app()

        @app.get("/kapali")
        def kapali():
            raise HTTPException(status_code=503)

        response = self.client(app).get("/kapali")

        self.assertEqual(503, response.status_code)
        self.assertEqual(["http_5xx"], self.kinds())

    def test_exception_handler_exception_500_tek_kayit(self):
        # Exception/500 işleyicisi ServerErrorMiddleware'e bağlanır; hata yine
        # bizim katmanımızdan geçer.
        app = self.app()

        @app.exception_handler(Exception)
        async def hepsi(request, exc):
            return PlainTextResponse("özür dileriz", status_code=500)

        response = self.client(app).get("/urun/3/patlat")

        self.assertEqual(500, response.status_code)
        self.assertEqual("özür dileriz", response.text)

        events = self.events()
        self.assertEqual(["exception"], [event["kind"] for event in events])
        self.assertEqual("RuntimeError", events[0]["exception_class"])

    def test_sinifa_bagli_isleyici_5xx_donerse_stackle_raporlanir(self):
        # ValueError işleyicisi içteki ExceptionMiddleware'de çalışır, hata bize
        # ulaşmaz; sarmalayıcı olmadan yalnızca stack'siz http_5xx giderdi.
        app = self.app()

        @app.exception_handler(ValueError)
        def deger_hatasi(request, exc):
            return PlainTextResponse("sunucu", status_code=500)

        response = self.client(app).get("/deger")

        self.assertEqual(500, response.status_code)
        self.assertEqual("sunucu", response.text)

        events = self.events()
        self.assertEqual(["exception"], [event["kind"] for event in events])
        self.assertEqual("ValueError", events[0]["exception_class"])
        self.assertEqual("/deger", events[0]["route"])

    def test_sinifa_bagli_isleyici_4xx_donerse_gonderilmez(self):
        app = self.app()

        @app.exception_handler(ValueError)
        async def deger_hatasi(request, exc):
            return PlainTextResponse("geçersiz", status_code=400)

        response = self.client(app).get("/deger")

        self.assertEqual(400, response.status_code)
        self.assertEqual([], self.events())

    def test_lifespan_gecer(self):
        with self.client(self.app()) as client:
            self.assertEqual(200, client.get("/urun/1").status_code)

        self.assertEqual([], self.events())

    def test_router_oneki_ve_mount_desene_eklenir(self):
        from fastapi import APIRouter

        from nabiz.asgi import NabizASGIMiddleware

        router = APIRouter(prefix="/v1")

        @router.get("/siparis/{siparis_id}")
        def siparis(siparis_id: int):
            raise RuntimeError("router")

        sub = FastAPI()
        sub.include_router(router)

        app = FastAPI()
        app.mount("/api", sub)
        app.add_middleware(NabizASGIMiddleware, hook_process_errors=False)

        self.client(app).get("/api/v1/siparis/9")

        events = self.events()
        self.assertEqual(["exception"], [event["kind"] for event in events])
        self.assertEqual("/api/v1/siparis/{siparis_id}", events[0]["route"])

    def _deger_isleyicili(self, app):
        @app.exception_handler(ValueError)
        def deger_hatasi(request, exc):
            return PlainTextResponse("sunucu", status_code=500)

        return app

    def test_isleyici_sarma_ara_katman_sirasindan_bagimsiz(self):
        # Nabız'dan sonra eklenen katman Nabız ile ExceptionMiddleware arasına
        # değil, dışına girer; ama önce eklenen (GZip) araya girer. İkisi de çalışmalı.
        from starlette.middleware.cors import CORSMiddleware
        from starlette.middleware.gzip import GZipMiddleware

        from nabiz.asgi import NabizASGIMiddleware

        for sonra in (GZipMiddleware, CORSMiddleware):
            self.hub.requests.clear()
            app = FastAPI()
            self._deger_isleyicili(app)

            @app.get("/deger")
            def deger():
                raise ValueError("geçersiz")

            # Önce Nabız'ın içine girecek katman, sonra Nabız.
            app.add_middleware(sonra, **({"allow_origins": ["*"]} if sonra is CORSMiddleware else {}))
            app.add_middleware(NabizASGIMiddleware, hook_process_errors=False)

            self.assertEqual(500, self.client(app).get("/deger").status_code)
            self.assertEqual(["exception"], self.kinds(), sonra.__name__)

    def test_elle_sarilan_uygulamada_isleyici_ilk_istekten_sonra_sarilir(self):
        from nabiz.asgi import NabizASGIMiddleware

        app = FastAPI()
        self._deger_isleyicili(app)

        @app.get("/deger")
        def deger():
            raise ValueError("geçersiz")

        client = self.client(NabizASGIMiddleware(app, hook_process_errors=False))
        client.get("/deger")
        self.reporter.flush(5)
        self.hub.requests.clear()

        client.get("/deger")

        self.assertEqual(["exception"], self.kinds())

    def test_arka_plan_gorevi_yavas_istek_sayilmaz(self):
        import time as _time

        from fastapi import BackgroundTasks

        app = self.app()

        @app.get("/arka")
        def arka(tasks: BackgroundTasks):
            tasks.add_task(_time.sleep, 0.3)
            return {"tamam": True}

        self.assertEqual(200, self.client(app).get("/arka").status_code)
        self.assertEqual([], self.events())

    def test_mount_edilen_alt_uygulamadaki_katman_cift_kayit_acmaz(self):
        import time as _time

        from nabiz.asgi import NabizASGIMiddleware

        sub = FastAPI()

        @sub.get("/yavas/{kod}")
        def yavas(kod: str):
            _time.sleep(0.15)
            return {"kod": kod}

        sub.add_middleware(NabizASGIMiddleware, hook_process_errors=False)

        app = FastAPI()
        app.mount("/alt", sub)
        app.add_middleware(NabizASGIMiddleware, hook_process_errors=False)

        self.client(app).get("/alt/yavas/abc")

        events = self.events()
        self.assertEqual(["slow_request"], [event["kind"] for event in events])
        self.assertEqual("GET /alt/yavas/{kod}", events[0]["route"])

    def test_gonderilmeyecek_istekte_rota_deseni_hesaplanmaz(self):
        from unittest import mock

        import nabiz.asgi

        with mock.patch.object(nabiz.asgi, "route_pattern", wraps=nabiz.asgi.route_pattern) as spy:
            client = self.client(self.app())
            client.get("/urun/1")
            self.assertEqual(0, spy.call_count)

            client.get("/bakim")
            self.assertEqual(1, spy.call_count)

    def test_sonradan_init_edilen_raporlayici_kullanilir(self):
        import nabiz

        client = self.client(self.app())
        yeni = nabiz.init(url=self.hub.url, key="yeni-proje", secret=SECRET, timeout=2.0)

        client.get("/urun/1/patlat")
        yeni.flush(5)

        self.assertTrue(self.hub.requests)
        self.assertTrue(all("/yeni-proje/" in r["path"] for r in self.hub.requests))


@unittest.skipIf(FastAPI is None, "fastapi/starlette kurulu değil")
class StarletteTest(_Base):
    def app(self):
        from starlette.applications import Starlette
        from starlette.middleware import Middleware
        from starlette.routing import Mount, Route

        from nabiz.asgi import NabizASGIMiddleware

        def urun_patlat(request):
            raise RuntimeError("starlette hatası")

        def bakim(request):
            return PlainTextResponse("bakım", status_code=503)

        return Starlette(
            routes=[
                Route("/urun/{urun_id:int}/patlat", urun_patlat),
                Mount("/yonetim", routes=[Route("/kayit/{kod}", urun_patlat)]),
                Route("/bakim/{bolum}", bakim),
            ],
            middleware=[Middleware(NabizASGIMiddleware, hook_process_errors=False)],
        )

    def test_istisna_rota_deseniyle_tek_kayit(self):
        response = TestClient(self.app(), raise_server_exceptions=False).get("/urun/5/patlat")

        self.assertEqual(500, response.status_code)

        events = self.events()
        self.assertEqual(["exception"], [event["kind"] for event in events])
        self.assertEqual("/urun/{urun_id:int}/patlat", events[0]["route"])

    def test_mount_altindaki_desen(self):
        TestClient(self.app(), raise_server_exceptions=False).get("/yonetim/kayit/abc")

        events = self.events()
        self.assertEqual("/yonetim/kayit/{kod}", events[0]["route"])

    def test_hatasiz_5xx_desenle_raporlanir(self):
        TestClient(self.app()).get("/bakim/depo")

        events = self.events()
        self.assertEqual(["http_5xx"], [event["kind"] for event in events])
        self.assertEqual("GET /bakim/{bolum}", events[0]["route"])

    def test_middleware_listesinde_nabiz_disarida_iken_isleyici_sarilir(self):
        from starlette.applications import Starlette
        from starlette.middleware import Middleware
        from starlette.middleware.cors import CORSMiddleware
        from starlette.routing import Route

        from nabiz.asgi import NabizASGIMiddleware

        def deger(request):
            raise ValueError("geçersiz")

        def isleyici(request, exc):
            return PlainTextResponse("sunucu", status_code=500)

        app = Starlette(
            routes=[Route("/deger/{kod}", deger)],
            middleware=[
                Middleware(NabizASGIMiddleware, hook_process_errors=False),
                Middleware(CORSMiddleware, allow_origins=["*"]),
            ],
            exception_handlers={ValueError: isleyici},
        )

        response = TestClient(app).get("/deger/x")

        self.assertEqual(500, response.status_code)
        events = self.events()
        self.assertEqual(["exception"], [event["kind"] for event in events])
        self.assertEqual("/deger/{kod}", events[0]["route"])

    def test_starlette_deseni_onbellekten_gelir(self):
        from unittest import mock

        import nabiz.asgi

        nabiz.asgi._CACHE.clear()
        client = TestClient(self.app())

        with mock.patch("starlette.routing.compile_path", wraps=__import__("starlette.routing", fromlist=["x"]).compile_path) as spy:
            client.get("/bakim/a")
            first = spy.call_count
            client.get("/bakim/b")

        self.assertGreater(first, 0)
        self.assertEqual(first, spy.call_count)
        self.assertEqual(["GET /bakim/{bolum}"] * 2, [e["route"] for e in self.events()])

    def test_istisna_yutulmaz(self):
        with self.assertRaises(RuntimeError):
            TestClient(self.app()).get("/urun/5/patlat")


if __name__ == "__main__":
    unittest.main()
