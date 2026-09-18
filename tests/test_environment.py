import io
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nabiz.reporter import Reporter, normalize_env  # noqa: E402


class EnvironmentTest(unittest.TestCase):
    """Hub yalnızca production/staging/local kabul ediyor. Tanınmayan değer
    eskiden sessizce production sayılıyordu: test verisi canlıya karışıyordu.
    Tablo Node ve Laravel paketleriyle aynı."""

    def test_takma_adlar_cevrilir(self):
        for girdi, beklenen in (
            (None, "production"), ("", "production"), ("prod", "production"), ("Live", "production"),
            ("stage", "staging"), ("UAT", "staging"), ("preprod", "staging"),
            ("development", "local"), ("dev", "local"), ("testing", "local"), ("test", "local"),
            ("production", "production"), ("staging", "staging"), ("local", "local"),
        ):
            self.assertEqual(beklenen, normalize_env(girdi), girdi)

    def test_taninmayan_ortam_production_sayilmaz(self):
        self.assertEqual("qa-eu", normalize_env("qa-eu"))
        self.assertEqual("qa-eu", Reporter(env="qa-eu").env)

    def test_durum_taninmayan_ortamda_hata_verir(self):
        from nabiz import cli

        ortam = {"NABIZ_URL": "https://hub.ornek", "NABIZ_KEY": "k", "NABIZ_SECRET": "a" * 64, "NABIZ_ENV": "qa-eu",
                 # Güncelleme denetimi ağa çıkmasın.
                 "NABIZ_DURUM_CEVRIMDISI": "1"}
        cikti, hata = io.StringIO(), io.StringIO()

        with mock.patch.dict(os.environ, ortam), mock.patch.object(cli, "read_env", return_value=ortam), \
                redirect_stdout(cikti), redirect_stderr(hata):
            kod = cli.main([])

        self.assertNotEqual(0, kod)
        self.assertIn("kabul edilmez", hata.getvalue())


if __name__ == "__main__":
    unittest.main()
