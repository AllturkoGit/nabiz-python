"""Kurulum teşhisi — ``nabiz-durum``.

Paketin en pahalı arıza biçimi için var: **sessiz çalışmama.** Yapılandırma
eksikken ya da secret yanlışken hiçbir şey patlamaz, hiçbir log düşmez — hub
geçersiz isteğe de 204 döner (saldırgana geri bildirim verilmez). Sonuç,
kimsenin fark etmediği bir izleme kurulumu.

Komut tek başına "çalışıyor" diyemez: hub geçerli ile geçersiz imzayı dışarıya
aynı yanıtla karşılar. Yaptığı iş, yerelde yanlış olan ne varsa göstermek ve
doğrulamanın hub panelinden yapılacağını söylemek.
"""

import os
import sys

from . import __version__, init, report, reporter
from .env import env as read_env

#: Panelden gelen secret'in uzunluğu. En sık kurulum hatası eksik kopyalamadır
#: ve sonucu sessizce hiçbir şey göndermemektir.
SECRET_LENGTH = 64


def _line(label, value):
    print(f"  {label:<18} {value}")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv

    # Süreç ortamı VE .env birlikte okunur. Yalnızca os.environ'a bakan bir
    # teşhis, .env doğru doldurulmuş bir kurulumda "TANIMSIZ" der — teşhis
    # aracının yanlış teşhis koyması, hiç teşhis koymamaktan kötüdür.
    values = read_env()
    secret = values.get("NABIZ_SECRET", "")
    url = values.get("NABIZ_URL", "")

    print("")
    _line("SDK sürümü", __version__)
    _line("Etkin", "HAYIR (NABIZ_ENABLED=false)" if values.get("NABIZ_ENABLED") == "false" else "evet")
    _line("Hub adresi", url or "TANIMSIZ")
    _line("Proje anahtarı", values.get("NABIZ_KEY") or "TANIMSIZ")
    _line("Secret uzunluğu", f"{len(secret)} karakter" if secret else "TANIMSIZ")
    _line("Ortam", values.get("NABIZ_ENV") or os.environ.get("APP_ENV") or "production")
    _line("Python", sys.version.split()[0])
    print("")

    problems = []

    if values.get("NABIZ_ENABLED") == "false":
        problems.append("NABIZ_ENABLED=false — hiçbir veri gönderilmez.")

    missing = [key for key in ("NABIZ_URL", "NABIZ_KEY", "NABIZ_SECRET") if not values.get(key)]

    if missing:
        problems.append(f"{', '.join(missing)} tanımlı değil.")

    if secret and len(secret) != SECRET_LENGTH:
        problems.append(
            f"NABIZ_SECRET {SECRET_LENGTH} karakter olmalı, {len(secret)} karakter. "
            "Eksik kopyalanmış olabilir."
        )

    if url.startswith("http://"):
        problems.append("NABIZ_URL http:// ile başlıyor — secret imzası şifresiz hat üzerinden gider.")

    if problems:
        for problem in problems:
            print(f"  ✗ {problem}", file=sys.stderr)
        print("")

        return 1

    print("  ✓ Yapılandırma tamam.")

    init()

    if "--test" in argv:
        # Gerçek bir hata raporlanır: hem taşıma hem temizlik sınanmış olur.
        # Sonuç okunuyor, "gönderdim" varsayılmıyor — koşulsuz başarı yazan
        # bir teşhis, ağ koptuğunda da "✓" der ve kuran kişi kurulumu çalışır
        # sanır.
        result = report(RuntimeError("nabiz-durum --test ile üretilen sınama olayı"), block=True)

        if not _report_result("Sınama olayı", result):
            return 1

    # --nabiz: bağlantıyı panele hata düşürmeden sınar. --test tek kurulumu
    # doğrularken doğru; onlarca kurulumu gezen bir güncelleme döngüsünde ise
    # panele onlarca sahte hata bırakır — izleme aracının kendi gürültüsünü
    # üretmesi.
    if "--nabiz" in argv:
        if not _report_result("Canlılık isteği", reporter().heartbeat(block=True)):
            return 1

    print("")
    print("  Verinin ulaştığı yalnızca hub panelinden doğrulanır:")
    print('  proje satırında bağlantı durumu "Bağlı" görünmelidir.')
    print("  Hub geçersiz imzaya da 204 döner; buradan anlaşılmaz.")
    print("")

    return 0


def _report_result(label, result):
    if result and result.get("sent"):
        print(f"  ✓ {label} gönderildi (HTTP {result.get('status')}).")

        return True

    reason = (result or {}).get("error") or f"HTTP {(result or {}).get('status')}"
    print(f"  ✗ {label} GÖNDERİLEMEDİ: {reason}", file=sys.stderr)
    print("")

    return False


if __name__ == "__main__":
    sys.exit(main())
