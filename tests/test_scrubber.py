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


    # Yükleme dosya adları okunur kalmalı: zaman damgası kart, uzun ad jeton
    # sanılıyordu. Beklenenler hub Scrubber'ıyla ortak vektörlerden.
    def test_yukleme_dosya_adi_okunur_kalir(self):
        for yol in (
            "/uploads/discount/kampanya-gorseli-yaz-indirimi-1726571234567-752066249.jpeg",
            "/uploads/sliders/slider-slider-1726571234567-249230604-1726571239999-875783343.png",
            "/uploads/products/urun-1795123456789-123456789.png",
        ):
            self.assertEqual(yol, scrubber.path(yol))

    def test_kart_yalnizca_gercekse_maskelenir(self):
        self.assertEqual("kart [kart] red", scrubber.text("kart 4111111111111111 red", 500))
        self.assertEqual("[kart] red", scrubber.text("378282246310005 red", 500))
        self.assertEqual("saat 1726571234567 geçti", scrubber.text("saat 1726571234567 geçti", 500))
        self.assertEqual("no 4111111111111112", scrubber.text("no 4111111111111112", 500))
        # Luhn'u tutan damga: yalnızca ilk hane kuralı ayırıyor.
        self.assertEqual("saat 1726571234573 geçti", scrubber.text("saat 1726571234573 geçti", 500))

    def test_90_onekli_telefon_maskelenir(self):
        # Sol sınır eklenince + olmadan 90 ön eki sızıyordu (önceden "9[telefon]").
        self.assertEqual("tel [telefon]", scrubber.text("tel 905321234567", 500))
        self.assertEqual("tel [telefon]", scrubber.text("tel 90 532 123 45 67", 500))

    def test_rastgele_diziler_yeni_kuralla_maskelenir(self):
        for girdi in (
            "x 3f2a1b4c-5d6e-4f70-8a9b-0c1d2e3f4a5b y",
            "x ghp_16C7e42F292c6912E7710c838347Ae178B4a y",
            "x a1b2c3d4-e5f6a7b8-c9d0e1f2-a3b4c5d6 y",
        ):
            self.assertEqual("x [jeton] y", scrubber.text(girdi, 500))

if __name__ == "__main__":
    unittest.main()
