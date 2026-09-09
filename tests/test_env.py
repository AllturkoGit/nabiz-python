import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nabiz import env as env_module  # noqa: E402


class EnvTest(unittest.TestCase):
    def setUp(self):
        self.previous_cwd = os.getcwd()
        self.directory = tempfile.mkdtemp()
        os.chdir(self.directory)
        env_module.forget()

        self.addCleanup(self._restore)

    def _restore(self):
        os.chdir(self.previous_cwd)
        env_module.forget()

        for key in ("NABIZ_URL", "NABIZ_KEY", "APP_ENV"):
            os.environ.pop(key, None)

    def write(self, name, content):
        Path(self.directory, name).write_text(content, encoding="utf-8")

    def test_env_dosyasi_okunur(self):
        # Asıl gerekçe: nabiz-durum ayrı bir süreç, uygulamanın .env'i
        # yüklenmez ve yalnızca os.environ'a bakan teşhis "TANIMSIZ" derdi.
        self.write(".env", "NABIZ_URL=https://hub.ornek.com\nNABIZ_KEY=lens\n")

        values = env_module.env()

        self.assertEqual("https://hub.ornek.com", values["NABIZ_URL"])
        self.assertEqual("lens", values["NABIZ_KEY"])

    def test_surec_ortami_dosyayi_yener(self):
        self.write(".env", "NABIZ_KEY=dosyadan\n")
        os.environ["NABIZ_KEY"] = "ortamdan"

        self.assertEqual("ortamdan", env_module.env()["NABIZ_KEY"])

    def test_ortama_ozel_dosya_once_gelir(self):
        os.environ["APP_ENV"] = "staging"
        self.write(".env", "NABIZ_KEY=genel\n")
        self.write(".env.staging", "NABIZ_KEY=staging\n")

        self.assertEqual("staging", env_module.env()["NABIZ_KEY"])

    def test_tirnak_yorum_ve_export_ayristirilir(self):
        self.write(
            ".env",
            "# yorum\nexport NABIZ_KEY='lens'\nNABIZ_URL=\"https://hub.ornek.com\"\n"
            "NABIZ_ENV=production # satır sonu yorumu\n",
        )

        values = env_module.env()

        self.assertEqual("lens", values["NABIZ_KEY"])
        self.assertEqual("https://hub.ornek.com", values["NABIZ_URL"])
        self.assertEqual("production", values["NABIZ_ENV"])

    def test_nabiz_disi_degiskenler_okunmaz(self):
        # Güvenlik sınırı: paket uygulamanın veritabanı şifresini hiç görmez.
        self.write(".env", "DB_PASSWORD=gizli\nNABIZ_KEY=lens\n")

        self.assertNotIn("DB_PASSWORD", env_module.env())

    def test_dosya_yoksa_patlamaz(self):
        self.assertIsInstance(env_module.env(), dict)


if __name__ == "__main__":
    unittest.main()
