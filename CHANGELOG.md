# Değişiklik günlüğü

## 0.1.0

İlk sürüm. Kardeş paket `@allturko/nabiz-node` 0.4.1 ile aynı kapsam.

- HMAC imzalı sunucu ucu gönderimi (`/api/i/{key}/server`), yönlendirme takip edilmez
- KVKK temizliği: e-posta, telefon, TCKN, IBAN, kart, jeton, SQL literalleri
- `exception` / `fatal` / `http_5xx` / `slow_request`
- Flask entegrasyonu (`nabiz.flask.NabizFlask`)
- Süreç kancaları: `sys.excepthook`, `threading.excepthook`
- 8 saatlik canlılık isteği
- `nabiz-durum` teşhis komutu (`--test`, `--nabiz`)

Node paketinden ayrışan yerler ve gerekçeleri:

- **Gönderim kuyruğu.** Node'da `fetch` zaten beklenmeyen bir promise; WSGI senkron
  çalıştığı için burada olaylar sınırlı bir kuyruğa bırakılır ve tek bir arka plan
  thread'i gönderir. Kuyruk dolduğunda olay düşürülür — bloke olmak izlenen uygulamayı
  yavaşlatırdı.
- **Tekilleştirme.** Node `WeakSet` kullanıyor; Python'da yerleşik istisnalar weakref
  kabul etmez (`weakref.ref(ValueError())` → `TypeError`), o yüzden işaret istisnanın
  üzerinde taşınır.
- **Fork temizliği.** Gunicorn `--preload` ile fork ediyor; `os.register_at_fork` ile
  çocuk süreçte kuyruk yeniden kurulur, yoksa olaylar ölü bir thread'e yazılırdı.
- **Unicode desenleri.** Python `re` `\p{L}` desteklemez; karşılıkları `\w` /
  `[^\W\d_]` ile kuruldu, gerçekçi girdide davranış aynıdır.
