import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_hub import FakeHub  # noqa: E402

from nabiz.client import MAX_BODY_BYTES, HubClient  # noqa: E402

SECRET = "s" * 64


class ClientTest(unittest.TestCase):
    def test_imza_hub_tarafinda_dogrulanir(self):
        with FakeHub(SECRET) as hub:
            client = HubClient(url=hub.url, key="proje", secret=SECRET)
            result = client.send({"kind": "exception", "msg": "deneme"})

        self.assertTrue(result["sent"])
        self.assertEqual(204, result["status"])
        self.assertEqual(1, len(hub.requests))
        self.assertTrue(hub.requests[0]["accepted"], "hub imzayı kabul etmeli")
        self.assertEqual("/api/i/proje/server", hub.requests[0]["path"])

    def test_yanlis_secret_hub_tarafinda_reddedilir(self):
        with FakeHub(SECRET) as hub:
            # Gerçek arıza biçimi: secret eksik kopyalanmış. Gönderen taraf
            # başarılı görünür (204), hub sessizce atar.
            HubClient(url=hub.url, key="proje", secret="s" * 63).send({"kind": "exception", "msg": "x"})

        self.assertFalse(hub.requests[0]["accepted"])

    def test_yapilandirma_eksikse_gonderilmez(self):
        result = HubClient(url=None, key=None, secret=None).send({"kind": "exception", "msg": "x"})

        self.assertEqual("yapilandirma-eksik", result["error"])

    def test_erisilemeyen_hub_hata_firlatmaz(self):
        # Kapalı port: bağlantı reddedilir.
        result = HubClient(url="http://127.0.0.1:9", key="k", secret=SECRET, timeout=0.5).send(
            {"kind": "exception", "msg": "x"}
        )

        self.assertFalse(result["sent"])
        self.assertIsNotNone(result["error"])

    def test_buyuk_govde_stack_dusurulerek_sigdirilir(self):
        with FakeHub(SECRET) as hub:
            client = HubClient(url=hub.url, key="proje", secret=SECRET)
            client.send({"kind": "exception", "msg": "kisa", "stack": "y" * 20000})

        request = hub.requests[0]
        self.assertLessEqual(len(request["raw"]), MAX_BODY_BYTES)
        self.assertTrue(request["accepted"], "kırpılmış gövde hub sınırına sığmalı")
        self.assertNotIn("stack", request["body"])

    def test_yonlendirme_takip_edilmez(self):
        # İmzalı gövde bilinmeyen bir adrese gönderilmemeli.
        from http.server import BaseHTTPRequestHandler, HTTPServer
        import threading

        class Redirector(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                self.send_response(302)
                self.send_header("Location", "http://baska.example/al")
                self.end_headers()

            def log_message(self, *_):
                pass

        server = HTTPServer(("127.0.0.1", 0), Redirector)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        host, port = server.server_address

        try:
            result = HubClient(url=f"http://{host}:{port}", key="k", secret=SECRET).send(
                {"kind": "exception", "msg": "x"}
            )
        finally:
            server.shutdown()
            server.server_close()

        self.assertEqual(302, result["status"])


if __name__ == "__main__":
    unittest.main()
