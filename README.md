# allturko-nabiz (Python)

[Nabız Hub](https://github.com/AllturkoGit/nabiz-hub) için Python raporlayıcı: sunucu
hataları, yavaş istekler, canlılık.

Bağımlılık yok. Build adımı yok. Python 3.9+.

Kardeş paketler: `allturko/nabiz` (Laravel), `@allturko/nabiz-node` (Node),
`t.js` (tarayıcı, hub reposunda `resources/sdk/t.js`).

---

## Kapsam — ve neden bu kadar dar

Bu paket **yalnızca sunucu tarafını** kapsar. Tarayıcı hataları hub'dan servis edilen
`t.js` ile toplanır; o dosya bilinçli olarak pakete taşınmadı — hosted olması bir
düzeltmenin dakikalar içinde tüm sitelere yayılmasını sağlıyor, paket olsaydı her
düzeltme için bütün projelerin yeniden dağıtılması gerekirdi.

Toplanmayanlar — yapılandırmayla dahi açılamaz:

IP adresi · User-Agent · istek gövdesi · query string **değerleri** (yalnızca yol) ·
oturum verisi · çerez · ham SQL literalleri

---

## Kurulum

```bash
pip install git+https://github.com/AllturkoGit/nabiz-python.git
```

`.env` dosyasına — kardeş paketlerle aynı değişken isimleri:

```env
NABIZ_ENABLED=true
NABIZ_URL=https://monitor.ornek.com
NABIZ_KEY=proje-anahtari
NABIZ_SECRET=<panelden alınan 64 karakterlik secret>
NABIZ_ENV=production
```

### Flask

```python
from flask import Flask
from nabiz.flask import NabizFlask

app = Flask(__name__)
NabizFlask(app)
```

Tek satır şunları kurar: yakalanmamış istisnalar (`teardown_request`), 5xx ve yavaş
istekler (`after_request`), süreç düzeyi kancalar (`sys.excepthook`,
`threading.excepthook`) ve 8 saatlik canlılık isteği.

### Çerçevesiz

```python
import nabiz

nabiz.hook_process()          # kancalar + canlılık
nabiz.report(error)           # elle bildirim
```

### Kurulumu doğrulayın

```bash
nabiz-durum
```

Bu adım atlanmamalı. Paketin en pahalı arıza biçimi **sessiz çalışmamadır**: secret
eksik kopyalanmışsa hiçbir şey patlamaz, hiçbir log düşmez — hub geçersiz imzaya da
`204` döner. Kurulum aylarca çalışmıyor olabilir ve o sessizlik "sorun yok" sanılır.

```bash
nabiz-durum --test    # gerçek bir sınama olayı — panelde hata olarak görünür
nabiz-durum --nabiz   # yalnızca canlılık isteği — panele hata düşürmez
```

`--test` tek bir kurulumu doğrularken doğru seçim. **Onlarca kurulumu gezen bir
güncelleme döngüsünde `--nabiz` kullanılır** — `--test` orada panele onlarca sahte hata
bırakır, yani izleme aracı kendi gürültüsünü üretir.

Verinin gerçekten ulaştığı yalnızca **hub panelinden** doğrulanır: proje satırındaki
bağlantı durumu `Bağlı` görünmelidir. Komut bunu kendi başına söyleyemez, çünkü hub
geçerli ile geçersiz imzayı dışarıya aynı yanıtla karşılar.

---

## Yapılandırma

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `NABIZ_ENABLED` | `true` | `false` iken hiçbir veri gönderilmez |
| `NABIZ_URL` | — | Hub adresi (https) |
| `NABIZ_KEY` | — | Proje anahtarı |
| `NABIZ_SECRET` | — | 64 karakterlik imza secret'i |
| `NABIZ_ENV` | `production` | `production` / `staging` / `local` |
| `NABIZ_RELEASE` | — | Sürüm etiketi (commit sha vb.) |
| `NABIZ_TIMEOUT` | `2.0` | Gönderim zaman aşımı (sn) |
| `NABIZ_SLOW_REQUEST_MS` | `1000` | Yavaş istek eşiği |

Ortam değişkenleri `os.environ` ve `.env` / `.env.local` / `.env.<APP_ENV>`
dosyalarından okunur; süreç ortamı her zaman kazanır. Yalnızca `NABIZ_` önekli
anahtarlar okunur.

---

## Neler raporlanır

| Tür | Ne zaman |
|---|---|
| `exception` | Yakalanmamış istisna, `report()` çağrısı |
| `fatal` | `MemoryError`, `RecursionError`, `SystemError` — yorumlayıcının sınırına çarpmak |
| `http_5xx` | Yanıt kodu ≥ 500 |
| `slow_request` | Süre ≥ `NABIZ_SLOW_REQUEST_MS` |

Başarılı ve hızlı istekler **raporlanmaz**: her isteği göndermek izlenen uygulamaya da
hub'a da yük olurdu.

---

## Davranış garantileri

1. **Hata yutulmaz.** Handler zinciri korunur, `raise` engellenmez.
2. **Süreç yönetimine karışılmaz.** `sys.exit` çağrılmaz, mevcut `excepthook` zincirlenir.
3. **Kendi hatasını raporlamaz.** Tüm SDK kodu `try/except` ile sarılır.
4. **Kullanıcı isteğini bekletmez.** Gönderim arka plan thread'inden, kısa zaman aşımıyla.
5. **Hub erişilemezse sessizce vazgeçilir.**
6. **`NABIZ_ENABLED=false` iken hiçbir veri gönderilmez.**

---

## Test

```bash
python -m unittest discover -s tests
```

Testler hub'ın imza doğrulamasını (`VerifyProjectSignature`) ve gövde sınırlarını
birebir uygulayan sahte bir hub'a karşı koşar: imzanın gerçekten kabul edilip
edilmediği burada görülür, "204 aldım" demek yeterli değildir.
