import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nabiz import scrubber  # noqa: E402


class ScrubberTest(unittest.TestCase):
    def test_eposta_maskelenir(self):
        self.assertEqual("[eposta] ile giris", scrubber.text("ahmet@ornek.com ile giris", 500))

    def test_turkce_harfli_eposta_maskelenir(self):
        # \p{L} karşılığı Python'da \w ile kuruldu; Türkçe harfler kapsanmalı.
        self.assertEqual("[eposta]", scrubber.text("şükrü@örnek.com.tr", 500))

    def test_yol_icindeki_eposta_yolu_yutmaz(self):
        # Gevşek desen ([^\s@]+) bütün yolu maskeliyordu.
        self.assertEqual("/kullanici/[eposta]/profil", scrubber.path("/kullanici/a@b.com/profil"))

    def test_query_string_atilir(self):
        self.assertEqual("/ara", scrubber.path("/ara?q=gizli&token=abc"))

    def test_kimlik_bilgileri_maskelenir(self):
        self.assertEqual("[tckn]", scrubber.text("12345678901", 500))
        self.assertEqual("[telefon]", scrubber.text("05321234567", 500))
        self.assertEqual("[iban]", scrubber.text("TR330006100519786457841326", 500))
        self.assertEqual("[kart]", scrubber.text("4111 1111 1111 1111", 500))

    def test_uzun_jeton_maskelenir(self):
        self.assertEqual("[jeton]", scrubber.text("a" * 40, 500))

    def test_kisa_kelime_maskelenmez(self):
        self.assertEqual("ValueError kisa mesaj", scrubber.text("ValueError kisa mesaj", 500))

    def test_sql_literalleri_normalize_edilir(self):
        self.assertEqual(
            "select * from users where email = ? and id = ?",
            scrubber.sql("select * from users where email = 'a@b.com' and id = 42"),
        )

    def test_in_listesi_tek_soru_isaretine_iner(self):
        self.assertEqual("id IN (?)", scrubber.sql("id IN (1, 2, 3)"))

    def test_sqlli_mesajda_deger_sizmaz(self):
        message = scrubber.message(
            "duplicate key value violates constraint: Key (email)=('a@b.com') exists",
            contains_sql=True,
        )

        self.assertNotIn("a@b.com", message)

    def test_limit_uygulanir(self):
        # Boşluklu metin: tek parça uzun dizi olsaydı önce [jeton] olurdu.
        self.assertEqual(10, len(scrubber.text("ab " * 100, 10)))

    def test_bos_deger_none_doner(self):
        self.assertIsNone(scrubber.text("", 10))
        self.assertIsNone(scrubber.path(None))
        self.assertIsNone(scrubber.sql(""))


if __name__ == "__main__":
    unittest.main()
