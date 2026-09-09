"""Kişisel veri temizliği — gönderimden ÖNCE uygulanır.

Hub tarafında aynı temizlik tekrar yapılır. İkisi de gereklidir: hub kendini
savunur, paket ise kişisel veriyi ağa hiç çıkarmaz. Bir sızıntı olacaksa ilk
savunma hattı burasıdır.

Desenler kardeş paketlerle (``allturko/nabiz`` PHP, ``@allturko/nabiz-node``)
aynı davranmak zorundadır: ayrışırlarsa aynı hata iki SDK'da farklı maskelenir,
parmak izi bölünür ve panelde tek hata iki satır olarak görünür.

Tek bilinçli sapma Unicode özellik kaçışlarındadır: Python'un ``re`` modülü
``\\p{L}`` desteklemez. Karşılıkları ``\\w`` / ``[^\\W\\d_]`` ile kuruldu —
``re`` str desenlerinde varsayılan olarak Unicode farkındadır, yani "ş", "ü"
gibi harfler de kapsanır. Fark yalnızca e-posta alan adındaki alt çizgide
kalır (bu paket onu da maskeler); gerçekçi girdide davranış aynıdır.
"""

import re
from urllib.parse import urlsplit

PATTERNS = [
    # E-posta. Gevşek bir sürüm ([^\s@]+) eğik çizgiyi de yutar ve
    # "/kullanici/a@b.com/profil" yolunun tamamını maskelerdi.
    (re.compile(r"[\w.%+-]+@[\w.-]+\.[^\W\d_]{2,}"), "[eposta]"),
    (re.compile(r"\bTR(?:[\s-]?\d){24}\b", re.IGNORECASE), "[iban]"),
    (re.compile(r"\b\d(?:[\s-]?\d){12,18}\b"), "[kart]"),
    (re.compile(r"\b[1-9]\d{10}\b"), "[tckn]"),
    (re.compile(r"(?:\+90|0)?[\s-]?5\d{2}[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}\b"), "[telefon]"),
    # Uzun rastgele diziler: oturum kimliği, API anahtarı, jeton, hash.
    # 24 hane eşiği bilinçli: oturum kimlikleri 40, API anahtarları 32+
    # karakterdir; normal kelimeler ve sınıf adları bu uzunluğa ulaşmaz.
    (re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{23,}"), "[jeton]"),
]

_SQL_LITERALS = [
    (re.compile(r"'(?:[^']|'')*'"), "?"),
    (re.compile(r'"(?:[^"]|"")*"'), "?"),
    (re.compile(r"\b\d+(?:\.\d+)?\b"), "?"),
    (re.compile(r"\b(IN)\s*\(\s*\?(?:\s*,\s*\?)+\s*\)", re.IGNORECASE), r"\1 (?)"),
]


def text(value, limit):
    """Maskele ve kırp. Boş değer ``None`` döner — hub'a boş alan gitmez."""
    if value is None or value == "":
        return None

    result = str(value)

    for pattern, replacement in PATTERNS:
        result = pattern.sub(replacement, result)

    return result[:limit]


def path(value):
    """Query string ve fragment atılır; yalnızca yol kalır (M3)."""
    if not value:
        return None

    try:
        # Taban adres yalnızca göreli yolları çözmek için; dışarı çıkmıyor.
        parsed = urlsplit(str(value))
        result = parsed.path if parsed.path else str(value)
    except ValueError:
        result = str(value).split("?")[0].split("#")[0]

    return text(result, 300)


def sql(value):
    """SQL normalize: literal değerler ``?`` ile değiştirilir.

    ``where email = 'ahmet@ornek.com'`` → ``where email = ?``

    Hem KVKK gereği hem gruplama açısından doğru: aynı sorgu farklı
    parametrelerle çalıştığında tek parmak izinde toplanır.
    """
    if not value:
        return None

    result = str(value)

    for pattern, replacement in _SQL_LITERALS:
        result = pattern.sub(replacement, result)

    return text(re.sub(r"\s+", " ", result).strip(), 500)


def message(value, contains_sql=False):
    """Hata mesajı.

    Veritabanı sürücülerinin hataları SQL'i bağlanmış değerlerle taşır; önce
    SQL normalize edilir, sonra genel maskeleme uygulanır. Yalnızca sorgu
    alanını temizlemek yetmiyordu — asıl sızıntı mesajın kendisinden oluyordu.
    """
    if not value:
        return None

    result = str(value)

    if contains_sql:
        result = re.sub(r"'(?:[^']|'')*'", "?", result)
        result = re.sub(r'"(?:[^"]|"")*"(\s*=\s*)\S+', r'"?"\1?', result)

    return text(result, 500)


def stack(value):
    """Traceback kısaltılır ve maskelenir.

    site-packages satırları atılmaz — hatanın nerede olduğunu bulmak için
    zincirin tamamı gerekir — ama uzunluk sınırlanır.
    """
    return text(value, 2000)
