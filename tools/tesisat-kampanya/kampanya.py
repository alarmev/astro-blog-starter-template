#!/usr/bin/env python3
"""Tesisat firmalarına kampanya e-postası aracı.

Üç adım:
  bul     Google Places API ile tesisatçı / tesisat malzemesi satan firmaları bulur
          -> veri/firmalar.csv
  eposta  Firmaların web sitelerini tarayıp herkese açık e-posta adreslerini çıkarır
          -> veri/firmalar.csv (eposta sütunu doldurulur)
  gonder  Hazırladığınız şablonu SMTP üzerinden gönderir (varsayılan: deneme modu)
          -> veri/gonderim_log.csv

Sadece Python standart kütüphanesini kullanır; ek paket kurulumu gerekmez.
"""

import argparse
import csv
import html
import json
import os
import random
import re
import smtplib
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path
from string import Template

KOK = Path(__file__).resolve().parent
VERI = KOK / "veri"
FIRMALAR_CSV = VERI / "firmalar.csv"
LOG_CSV = VERI / "gonderim_log.csv"
RET_LISTESI = VERI / "ret_listesi.txt"

ALANLAR = ["firma_adi", "sehir", "adres", "telefon", "web", "eposta", "kaynak", "place_id"]

VARSAYILAN_ANAHTAR_KELIMELER = [
    "tesisatçı",
    "sıhhi tesisat",
    "tesisat malzemeleri",
    "su tesisatı malzemesi",
    "doğalgaz tesisatı",
]

USER_AGENT = "Mozilla/5.0 (compatible; TesisatKampanyaBot/1.0)"
EPOSTA_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# "info [at] firma [dot] com" gibi gizlenmiş adresler
GIZLI_RE = re.compile(
    r"([A-Za-z0-9._%+-]+)\s*[\[\(]\s*(?:at|@)\s*[\]\)]\s*([A-Za-z0-9-]+)"
    r"\s*[\[\(]\s*(?:dot|nokta|\.)\s*[\]\)]\s*([A-Za-z.]{2,})",
    re.I,
)
ILETISIM_YOLLARI = ["", "/iletisim", "/iletisim.html", "/contact", "/bize-ulasin", "/hakkimizda"]
GECERSIZ_UZANTILAR = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js")
GECERSIZ_PARCALAR = ("example.", "sentry", "wixpress", "domain.com", "email.com", "@2x", "yourdomain")


# --------------------------------------------------------------------------- ortak

def env_yukle():
    """KOK/.env dosyasını (varsa) ortam değişkenlerine yükler."""
    dosya = KOK / ".env"
    if not dosya.exists():
        return
    for satir in dosya.read_text(encoding="utf-8").splitlines():
        satir = satir.strip()
        if not satir or satir.startswith("#") or "=" not in satir:
            continue
        anahtar, deger = satir.split("=", 1)
        os.environ.setdefault(anahtar.strip(), deger.strip().strip('"').strip("'"))


def gerekli_env(ad):
    deger = os.environ.get(ad)
    if not deger:
        sys.exit(f"HATA: {ad} tanımlı değil. .env dosyasını kontrol edin (bkz. .env.example).")
    return deger


def csv_oku(yol):
    if not yol.exists():
        return []
    with yol.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def csv_yaz(yol, satirlar, alanlar=ALANLAR):
    yol.parent.mkdir(parents=True, exist_ok=True)
    with yol.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=alanlar, extrasaction="ignore")
        w.writeheader()
        w.writerows(satirlar)


def http_get(url, zaman_asimi=15):
    istek = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(istek, timeout=zaman_asimi) as yanit:
        if "text/html" not in yanit.headers.get("Content-Type", "text/html"):
            return ""
        return yanit.read(2_000_000).decode(yanit.headers.get_content_charset() or "utf-8", "replace")


# --------------------------------------------------------------------------- bul

def places_ara(api_key, sorgu, max_sonuc):
    """Google Places API (New) Text Search. Sayfa başına 20, en fazla 60 sonuç."""
    url = "https://places.googleapis.com/v1/places:searchText"
    basliklar = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,"
        "places.nationalPhoneNumber,places.websiteUri,nextPageToken",
    }
    govde = {"textQuery": sorgu, "languageCode": "tr", "regionCode": "TR", "pageSize": 20}
    sonuclar = []
    while len(sonuclar) < max_sonuc:
        istek = urllib.request.Request(url, json.dumps(govde).encode(), basliklar, method="POST")
        try:
            with urllib.request.urlopen(istek, timeout=30) as yanit:
                veri = json.load(yanit)
        except urllib.error.HTTPError as e:
            sys.exit(f"Places API hatası ({e.code}): {e.read().decode(errors='replace')}")
        sonuclar.extend(veri.get("places", []))
        token = veri.get("nextPageToken")
        if not token:
            break
        govde["pageToken"] = token
        time.sleep(2)
    return sonuclar[:max_sonuc]


def komut_bul(args):
    api_key = gerekli_env("GOOGLE_PLACES_API_KEY")
    mevcut = csv_oku(FIRMALAR_CSV)
    bilinen = {r["place_id"] for r in mevcut if r.get("place_id")}
    bilinen_web = {alan_adi(r["web"]) for r in mevcut if r.get("web")}
    kelimeler = args.kelime or VARSAYILAN_ANAHTAR_KELIMELER
    yeni = 0
    for sehir in args.sehir:
        for kelime in kelimeler:
            sorgu = f"{kelime} {sehir}"
            print(f"Aranıyor: {sorgu}")
            for p in places_ara(api_key, sorgu, args.max):
                web = p.get("websiteUri", "")
                if p["id"] in bilinen or (web and alan_adi(web) in bilinen_web):
                    continue
                bilinen.add(p["id"])
                if web:
                    bilinen_web.add(alan_adi(web))
                mevcut.append({
                    "firma_adi": p.get("displayName", {}).get("text", ""),
                    "sehir": sehir,
                    "adres": p.get("formattedAddress", ""),
                    "telefon": p.get("nationalPhoneNumber", ""),
                    "web": web,
                    "eposta": "",
                    "kaynak": "google_places",
                    "place_id": p["id"],
                })
                yeni += 1
    csv_yaz(FIRMALAR_CSV, mevcut)
    webli = sum(1 for r in mevcut if r.get("web"))
    print(f"\n{yeni} yeni firma eklendi. Toplam {len(mevcut)} firma, {webli} tanesinin web sitesi var.")
    print(f"Dosya: {FIRMALAR_CSV}\nSonraki adım: python3 kampanya.py eposta")


# --------------------------------------------------------------------------- eposta

def alan_adi(url):
    return urllib.parse.urlparse(url if "://" in url else "http://" + url).netloc.lower().removeprefix("www.")


def gecerli_eposta(e):
    e = e.lower().strip(".")
    return not e.endswith(GECERSIZ_UZANTILAR) and not any(p in e for p in GECERSIZ_PARCALAR)


def sayfadan_epostalar(metin):
    metin = html.unescape(metin)
    bulunan = set(EPOSTA_RE.findall(metin))
    for kul, alan, uzanti in GIZLI_RE.findall(metin):
        bulunan.add(f"{kul}@{alan}.{uzanti}")
    return {e.lower().strip(".") for e in bulunan if gecerli_eposta(e)}


def en_iyi_eposta(epostalar, site_alani):
    """Sitenin kendi alan adındaki ve info@/satis@ gibi adresleri öne alır."""
    def puan(e):
        kul, alan = e.split("@", 1)
        p = 0
        if alan.removeprefix("www.") == site_alani:
            p += 10
        if kul in ("info", "bilgi", "satis", "sales", "iletisim", "contact", "destek"):
            p += 5
        return -p, e
    return sorted(epostalar, key=puan)[0] if epostalar else ""


def siteyi_tara(web):
    taban = web if "://" in web else "http://" + web
    p = urllib.parse.urlparse(taban)
    kok = f"{p.scheme}://{p.netloc}"
    robots = urllib.robotparser.RobotFileParser(kok + "/robots.txt")
    try:
        robots.read()
    except Exception:
        robots = None
    epostalar = set()
    for yol in ILETISIM_YOLLARI:
        url = kok + yol
        if robots and not robots.can_fetch(USER_AGENT, url):
            continue
        try:
            epostalar |= sayfadan_epostalar(http_get(url))
        except Exception:
            continue
        if epostalar and yol:  # iletişim sayfasında bulduysak yeter
            break
        time.sleep(0.5)
    return en_iyi_eposta(epostalar, alan_adi(kok))


def komut_eposta(args):
    firmalar = csv_oku(FIRMALAR_CSV)
    if not firmalar:
        sys.exit(f"{FIRMALAR_CSV} boş. Önce 'bul' komutunu çalıştırın veya dosyayı elle doldurun.")
    hedef = [r for r in firmalar if r.get("web") and (args.yeniden or not r.get("eposta"))]
    print(f"{len(hedef)} web sitesi taranacak...")
    for i, r in enumerate(hedef, 1):
        e = siteyi_tara(r["web"])
        r["eposta"] = e
        print(f"[{i}/{len(hedef)}] {r['firma_adi'][:40]:40} {e or '-'}")
        if i % 10 == 0:
            csv_yaz(FIRMALAR_CSV, firmalar)  # ara kayıt
    csv_yaz(FIRMALAR_CSV, firmalar)
    epostali = sum(1 for r in firmalar if r.get("eposta"))
    print(f"\n{epostali}/{len(firmalar)} firmanın e-posta adresi var.")
    print("Listeyi gözden geçirin, sonra: python3 kampanya.py gonder  (önce deneme modu)")


# --------------------------------------------------------------------------- gonder

def ret_listesi():
    if not RET_LISTESI.exists():
        return set()
    return {s.strip().lower() for s in RET_LISTESI.read_text(encoding="utf-8").splitlines()
            if s.strip() and not s.startswith("#")}


def gonderilmisler():
    return {r["eposta"].lower() for r in csv_oku(LOG_CSV) if r.get("durum") == "gonderildi"}


def log_yaz(eposta, firma, durum, detay=""):
    yeni = not LOG_CSV.exists()
    LOG_CSV.parent.mkdir(parents=True, exist_ok=True)
    with LOG_CSV.open("a", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        if yeni:
            w.writerow(["zaman", "eposta", "firma_adi", "durum", "detay"])
        w.writerow([datetime.now().isoformat(timespec="seconds"), eposta, firma, durum, detay])


def mesaj_olustur(r, konu_t, html_t, metin_t, gonderen_ad, gonderen, ret_adresi):
    degiskenler = {k: (r.get(k) or "") for k in ALANLAR}
    degiskenler["firma_adi"] = degiskenler["firma_adi"] or "Değerli İş Ortağımız"
    degiskenler["ret_adresi"] = ret_adresi
    m = EmailMessage()
    m["Subject"] = konu_t.safe_substitute(degiskenler)
    m["From"] = formataddr((gonderen_ad, gonderen))
    m["To"] = r["eposta"]
    m["Reply-To"] = ret_adresi
    m["Message-ID"] = make_msgid(domain=gonderen.split("@")[-1])
    m["List-Unsubscribe"] = f"<mailto:{ret_adresi}?subject=RET>"
    m.set_content(metin_t.safe_substitute(degiskenler))
    if html_t:
        m.add_alternative(html_t.safe_substitute(degiskenler), subtype="html")
    return m


def smtp_baglan():
    host = gerekli_env("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT", "587"))
    kullanici = gerekli_env("SMTP_USER")
    sifre = gerekli_env("SMTP_PASSWORD")
    ctx = ssl.create_default_context()
    if port == 465:
        s = smtplib.SMTP_SSL(host, port, context=ctx, timeout=30)
    else:
        s = smtplib.SMTP(host, port, timeout=30)
        s.starttls(context=ctx)
    s.login(kullanici, sifre)
    return s


def komut_gonder(args):
    gonderen = gerekli_env("GONDEREN_EPOSTA")
    gonderen_ad = os.environ.get("GONDEREN_AD", "")
    ret_adresi = os.environ.get("RET_EPOSTA", gonderen)

    sablon_dizini = KOK / "sablon"
    konu_t = Template((sablon_dizini / "konu.txt").read_text(encoding="utf-8").strip())
    metin_t = Template((sablon_dizini / "kampanya.txt").read_text(encoding="utf-8"))
    html_yol = sablon_dizini / "kampanya.html"
    html_t = Template(html_yol.read_text(encoding="utf-8")) if html_yol.exists() else None

    engelli = ret_listesi() | gonderilmisler()
    gorulen = set()
    kuyruk = []
    for r in csv_oku(FIRMALAR_CSV):
        e = (r.get("eposta") or "").strip().lower()
        if not e or e in engelli or e in gorulen:
            continue
        gorulen.add(e)
        r["eposta"] = e
        kuyruk.append(r)
    kuyruk = kuyruk[: args.limit]

    if not kuyruk:
        print("Gönderilecek yeni adres yok (hepsi gönderilmiş, ret listesinde ya da e-postasız).")
        return

    if not args.gercek:
        print(f"DENEME MODU — {len(kuyruk)} e-posta gönderilecekti. Hiçbir şey gönderilmedi.\n")
        ornek = mesaj_olustur(kuyruk[0], konu_t, html_t, metin_t, gonderen_ad, gonderen, ret_adresi)
        print("---- Örnek mesaj ----")
        for b in ("From", "To", "Subject", "Reply-To", "List-Unsubscribe"):
            print(f"{b}: {ornek[b]}")
        print()
        print(ornek.get_body(("plain",)).get_content())
        print("---- Alıcılar ----")
        for r in kuyruk:
            print(f"  {r['eposta']:40} {r['firma_adi']}")
        print("\nGerçekten göndermek için: python3 kampanya.py gonder --gercek")
        return

    if args.test_adresi:
        kuyruk = [dict(kuyruk[0], eposta=args.test_adresi)]
        print(f"Test: tek mesaj {args.test_adresi} adresine gönderiliyor.")

    smtp = smtp_baglan()
    try:
        for i, r in enumerate(kuyruk, 1):
            m = mesaj_olustur(r, konu_t, html_t, metin_t, gonderen_ad, gonderen, ret_adresi)
            try:
                try:
                    smtp.send_message(m)
                except smtplib.SMTPServerDisconnected:
                    smtp = smtp_baglan()
                    smtp.send_message(m)
                if not args.test_adresi:
                    log_yaz(r["eposta"], r["firma_adi"], "gonderildi")
                print(f"[{i}/{len(kuyruk)}] gönderildi: {r['eposta']}")
            except smtplib.SMTPException as e:
                log_yaz(r["eposta"], r["firma_adi"], "hata", str(e))
                print(f"[{i}/{len(kuyruk)}] HATA {r['eposta']}: {e}")
            if i < len(kuyruk):
                time.sleep(args.bekleme + random.uniform(0, args.bekleme / 2))
    finally:
        try:
            smtp.quit()
        except Exception:
            pass


# --------------------------------------------------------------------------- main

def main():
    env_yukle()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    alt = ap.add_subparsers(dest="komut", required=True)

    b = alt.add_parser("bul", help="Google Places ile firma bul")
    b.add_argument("--sehir", nargs="+", required=True, help='Örn: --sehir İstanbul Ankara "Kocaeli Gebze"')
    b.add_argument("--kelime", nargs="+", help="Arama kelimeleri (varsayılan: tesisat ile ilgili 5 kelime)")
    b.add_argument("--max", type=int, default=60, help="Sorgu başına en fazla sonuç (<=60)")
    b.set_defaults(f=komut_bul)

    e = alt.add_parser("eposta", help="Web sitelerinden e-posta adreslerini çıkar")
    e.add_argument("--yeniden", action="store_true", help="E-postası olan firmaları da yeniden tara")
    e.set_defaults(f=komut_eposta)

    g = alt.add_parser("gonder", help="Kampanya e-postasını gönder (varsayılan: deneme modu)")
    g.add_argument("--gercek", action="store_true", help="Deneme modunu kapat, gerçekten gönder")
    g.add_argument("--limit", type=int, default=50, help="Bu çalıştırmada en fazla kaç e-posta (varsayılan 50)")
    g.add_argument("--bekleme", type=float, default=30, help="Mesajlar arası bekleme, saniye (varsayılan 30)")
    g.add_argument("--test-adresi", help="Sadece bu adrese tek bir örnek gönder (log'a yazılmaz)")
    g.set_defaults(f=komut_gonder)

    args = ap.parse_args()
    args.f(args)


if __name__ == "__main__":
    main()
