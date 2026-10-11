# Tesisat Kampanya Aracı

Tesisatçıları ve tesisat malzemesi satan firmaları bulup hazırladığınız kampanya e-postasını gönderen küçük bir komut satırı aracı. Sadece Python 3.9+ gerekir; ek paket yok.

```
bul  ──►  eposta  ──►  (listeyi kontrol et)  ──►  gonder (deneme)  ──►  gonder --gercek
```

## Kurulum

```bash
cd tools/tesisat-kampanya
cp .env.example .env     # sonra .env dosyasını doldurun
```

- **Google Places API anahtarı:** Google Cloud Console → yeni proje → "Places API (New)" etkinleştirin → Credentials → API key. Text Search ücretli bir API'dir ama Google'ın aylık ücretsiz kotası küçük kampanyalar için genelde yeterli; fiyatlandırmayı kendiniz kontrol edin.
- **SMTP:** Gmail kullanacaksanız 2 adımlı doğrulamayı açıp bir *Uygulama Şifresi* oluşturun. Gmail/Yandex günlük gönderim limitleri düşüktür (yüzlerce); daha fazlası için Brevo, Mailgun, Amazon SES gibi bir servisin SMTP bilgilerini ve kendi alan adınızı (SPF/DKIM ayarlı) kullanın, yoksa e-postalar spam'e düşer.

## 1. Firmaları bul

```bash
python3 kampanya.py bul --sehir İstanbul Ankara İzmir
python3 kampanya.py bul --sehir Bursa --kelime "tesisat malzemeleri" "pvc boru"
```

Her şehir × anahtar kelime için Google Places araması yapar, sonuçları `veri/firmalar.csv` dosyasına ekler (tekrarları atlar). Varsayılan kelimeler: tesisatçı, sıhhi tesisat, tesisat malzemeleri, su tesisatı malzemesi, doğalgaz tesisatı.

Elinizde başka bir liste varsa `veri/firmalar.csv` dosyasına aynı sütunlarla elle de ekleyebilirsiniz (`firma_adi,sehir,adres,telefon,web,eposta,kaynak,place_id`).

## 2. E-posta adreslerini çıkar

```bash
python3 kampanya.py eposta
```

Web sitesi olan her firmanın ana sayfasını ve iletişim sayfalarını (`/iletisim`, `/contact`, …) tarar; `robots.txt` kurallarına uyar. Sitenin kendi alan adındaki `info@`, `satis@` gibi adresleri tercih eder. Sonuç yine `veri/firmalar.csv`'ye yazılır.

👉 **Göndermeden önce CSV'yi Excel'de açıp gözden geçirin**, alakasız firmaları silin.

## 3. Şablonu hazırla

`sablon/` klasöründeki dosyaları düzenleyin:

| Dosya | İçerik |
|---|---|
| `konu.txt` | E-posta konusu |
| `kampanya.html` | HTML gövde (hazırladığınız tasarımı buraya yapıştırın) |
| `kampanya.txt` | Düz metin gövde (HTML göstermeyen istemciler için) |

Kullanılabilen değişkenler: `$firma_adi`, `$sehir`, `$adres`, `$telefon`, `$web`, `$eposta`, `$ret_adresi`. Metinde düz `$` işareti gerekiyorsa `$$` yazın.

## 4. Gönder

```bash
python3 kampanya.py gonder                                   # DENEME: kime gideceğini ve örnek mesajı gösterir
python3 kampanya.py gonder --gercek --test-adresi siz@ornek.com   # kendinize tek örnek gönderir
python3 kampanya.py gonder --gercek --limit 50 --bekleme 30       # gerçek gönderim
```

- Varsayılan olarak **deneme modundadır**; `--gercek` vermeden hiçbir şey gönderilmez.
- Her başarılı gönderim `veri/gonderim_log.csv`'ye yazılır; aynı adrese **ikinci kez gönderilmez**. Komutu her gün `--limit` ile tekrar çalıştırarak gönderimi günlere yayabilirsiniz.
- `veri/ret_listesi.txt` içindeki adreslere asla gönderilmez. "RET" yanıtı gelenleri buraya ekleyin.
- Her mesaja `List-Unsubscribe` başlığı ve ret açıklaması eklenir.

## Yasal not (Türkiye)

- 6563 sayılı Kanun ve Ticari İletişim Yönetmeliği'ne göre **esnaf ve tacirlere** gönderilen ticari elektronik iletiler için önceden onay şartı yoktur, ancak alıcının **ret hakkını kolayca kullanabilmesi** gerekir ve ret talebi 3 iş günü içinde uygulanmalıdır. Şablondaki ret metnini kaldırmayın.
- Ticari ileti gönderen hizmet sağlayıcıların **İYS (İleti Yönetim Sistemi)** kaydı yükümlülüğü bulunur; kendi durumunuzu kontrol edin.
- Gönderen kimliğiniz (firma adı, iletişim bilgisi) mesajda açıkça yer almalıdır.
- Bu araç yalnızca web sitelerinde herkese açık yayımlanmış kurumsal adresleri toplar; şahıs adreslerine gönderim yapmayın.

Bu bir hukuki danışmanlık değildir; büyük ölçekli gönderimden önce güncel mevzuatı kontrol edin.
