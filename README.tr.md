<p align="center"><img src="app.png" width="112" alt="Orbida simgesi"></p>

# Orbida

Orbida; YouTube, TikTok, Instagram, X ve
[yt-dlp](https://github.com/yt-dlp/yt-dlp)'nin desteklediği diğer sitelerden
video ve ses indirir. İki uygulaması var:

- **Windows**: Python ve CustomTkinter ile yazıldı.
- **Android**: Kivy ve KivyMD ile yazıldı.

İkisi de aynı indirme kodunu çalıştırır. Birleştirme, dönüştürme ve kırpma
için FFmpeg kullanır. Orbida'nın 1.0.2 sürümüne kadarki adı **Universal
Video Downloader** idi.

[English](README.md)

![Ana pencere](docs/images/main-window.png)

## İndirme

Her sürüm tek bir
[GitHub sürümüdür](https://github.com/DorDeorz/UniversalDownloader/releases/latest)
ve iki uygulamayı birlikte içerir.

| | Dosya | Gereksinim |
|---|---|---|
| Windows | `Orbida-Setup-<sürüm>.exe` | Windows 10 veya 11, 64 bit |
| Android | `Orbida-<sürüm>.apk` | Android 7 veya üstü, 64 bit ARM telefon |

Aynı sürümdeki `SHA256SUMS.txt`, iki dosyanın sağlama toplamlarını listeler.

**Windows.** Kurulum dosyasını çalıştırın. Yönetici izni istemeden
yalnızca sizin kullanıcınıza kurulur ve Başlat menüsüne eklenir.
Uygulamanın ihtiyaç duyduğu her şey içindedir: FFmpeg, ffprobe ve
yt-dlp'nin YouTube için kullandığı Deno. Kurulum dosyası kod imzalı
olmadığından SmartScreen "Windows bilgisayarınızı korudu" diyebilir.
**Ek bilgi**'ye, ardından **Yine de çalıştır**'a tıklayın. Bilgisayarda
Universal Video Downloader 1.0.x kuruluysa kurulum onu yerinde yükseltir ve
ayarlarınızı korur.

**Android.** APK dosyasını telefonda açın. Android, dosyayı açtığınız
tarayıcı veya dosya yöneticisi için "Bilinmeyen uygulamaları yükle" izni
ister. İzni verin, geri dönün ve **Yükle**'ye dokunun. Uygulama Google
Play'de olmadığı için Play Protect onu tarayabilir ya da bilinmeyen
geliştirici uyarısı gösterebilir. **Daha fazla ayrıntı**'ya, ardından
**Yine de yükle**'ye dokunun. Daha önce bir Android önizlemesi (0.x)
kurduysanız onu bir kez kaldırın: 1.0'ın uygulama kimliği yeni ve kendi
imza anahtarı var.

### Güncellemeler

İki uygulama da açılırken yeni sürüm olup olmadığına bakar ve yeni sürümü
sizin için kurar. Önce eskisini kaldırmanız gerekmez.

- **Windows.** Üst çubukta **x.y.z sürümüne güncelle** düğmesi çıkar. Düğme
  yeni kurulum dosyasını indirir, `SHA256SUMS.txt` ile doğrular, kurar ve
  Orbida'yı yeniden başlatır.
- **Android.** Android güncellemeyi onaylamanızı ister. Yalnızca kurulu
  uygulamayla aynı anahtarla imzalanmış bir güncellemeyi kurar.

Windows tarafının ayrıntıları için:
[docs/updates.md](docs/updates.md) (İngilizce).

## Özellikler

### İki uygulamada da

- **Bağlantıyı yapıştırın ya da paylaşın, sonra Analiz edin.** Video,
  süresiyle gösterilir. Oynatma listesinde kaç öğenin indirilebileceği
  gösterilir. Özel, silinmiş, yalnızca üyelere açık ve canlı yayın öğeleri,
  neden atlandıklarıyla listelenir.
- **Neyi kaydedeceğinizi seçin.** Sesli video ya da yalnızca ses. Bir
  kalite sınırı (4K'dan 360p'ye) ya da bir ses bit hızı. Video için MP4
  veya MKV. Ses için MP3, M4A, FLAC veya WAV.
- **Kırpma.** Videonun yalnızca bir kısmını indirin (ör. 0:10 ile 1:30
  arası). Süreler indirme başlamadan denetlenir.
- **Daha hızlı indirme.** Akış videoları (Instagram, X, canlı yayın) aynı
  anda birkaç parçayla iner. Kaç parça olacağını **Paralel bağlantı**
  ayarı belirler.
- **TikTok** çalışır: yt-dlp, tarayıcı gibi istek gönderir (curl_cffi).
- **Her öğenin bir sonucu olur.** Her öğe tamamlandı, başarısız, atlandı ya
  da iptal edildi olarak biter. Tamamlanmadıysa nedeni de yazılır. İptal
  edilen indirme yarım dosya bırakmaz.
- **Dosyalar birbirinin üzerine yazılmaz.** İkinci bir "Başlık.mp4",
  "Başlık (2).mp4" olur.
- **Geçmiş:** Biten indirmeler Aç ve Kaldır düğmeleriyle listelenir.
- **Ayarlar:**
  - tema ve vurgu rengi;
  - dil;
  - paralel bağlantı;
  - açılışta kopyalanmış bağlantıyı yapıştırma;
  - indirme sürerken cihazı uyanık tutma.

  Seçimleriniz hatırlanır.
- **Uygulama içinden güncelleme**, GitHub sürümlerinden.
- **Güvenli.** HTTPS sertifikaları her zaman doğrulanır. Hatalar
  gizlenmez, anlaşılır sözlerle gösterilir.

### Windows

- Yalnızca video modu, WebM ve Opus biçimleri.
- Oynatma listeleri bir seçim penceresiyle açılır. Seçilen öğeler numaralı
  adlarla kendi klasörlerine iner. Başarısız öğeler tek tıkla yeniden
  denenir.
- 25 arayüz dili vardır ve dil, yeniden başlatmadan değişir. Üç metin
  boyutu, koyu, açık ya da sistem teması ve sekiz vurgu rengi var.
- Pencere her metin boyutunda ekrana sığar ve görev çubuğunun üstünde
  kalır. Ayarlar pencerenin içinde açılır ve kaydırma gerektirmez.
- Geçmiş sayfasında Aç, Klasörde göster ve Kaldır düğmeleri var.
- Klavye kısayolları:
  - Enter analiz eder;
  - Ctrl+Enter indirir;
  - Esc iptal eder;
  - Ctrl+O klasör seçer;
  - Ctrl+, Ayarlar'ı açar.
- İndirme sürerken bilgisayar uyku moduna geçmez.
- Aynı anda uygulamanın tek kopyası çalışır. İndirme sürerken kapatmak
  önce sorar, sonra indirmeyi düzgünce durdurur.
- İndirilen dosyalar varsayılan olarak `İndirilenler\Orbida` klasörüne
  kaydedilir.

![Ayarlar](docs/images/settings.png)
![Geçmiş](docs/images/history.png)

### Android

- Material You tasarımı: İndir, Geçmiş ve Ayarlar sekmeleri. Android 12 ve
  üstünde renkler duvar kağıdınıza uyar.
- Herhangi bir uygulamadan bağlantıyı Orbida'ya **Paylaş**abilirsiniz.
  İsterseniz paylaşılan bağlantılar hemen analiz edilir.
- **Hesapsız YouTube.** YouTube "bot olmadığınızı doğrulayın" derse Orbida
  telefonun kendi tarayıcı motoru üzerinden yeniden dener. Oturum açmak
  mümkün ama gerekmez.
- Dosyalar `Download/Orbida` klasörüne kaydedilir ve galeri ile müzik
  uygulamalarında görünür. Geçmiş sekmesinde Aç, Paylaş ve Kaldır var.
- İndirme sürerken ekran açık kalır.
- İngilizce ve Türkçe.

Ayrıntılar: [android/README.md](android/README.md) (İngilizce).

## Adım adım neler yaptık

Proje çalışan bir Windows prototipi olarak başladı: dört dosyada yaklaşık
400 satır. Aşağıdaki her adım yayınlanmadan önce test edildi.

1. **İnceleme.** [ISSUES.md](ISSUES.md), prototipte bulunan 90 sorunu
   listeler:
   - Kırpma çöküyordu. Yalnızca video modu sesi bırakmıyordu. Yalnızca ses
     modu mp4 gibi video biçimleri sunuyordu.
   - HTTPS denetimleri kapalıydı ve hatalar gizleniyordu. Hiçbir şey
     inmese bile her iş "Bitti!" ile sonlanıyordu.
   - İş parçacıkları pencereyi doğrudan değiştiriyordu. Bu, pencereyi
     dondurabiliyor ya da çökertebiliyordu.
   - Aynı adlı dosyalar birbirinin üzerine yazılıyordu.
   - Kodun yeni bir kopyası FFmpeg olmadan açılıyordu.
   - Hiç test yoktu ve derleme yeniden üretilemiyordu.
2. **Temel düzeltmeler**
   ([#5](https://github.com/DorDeorz/UniversalDownloader/pull/5)). Özgün
   yapı korundu: pencere için `ui.py`, yt-dlp için `logic.py`.
   - Her mod söylediğini üretiyor.
   - Kırpma, paketlenmiş uygulamada da çalışıyor.
   - Aynı anda tek iş çalışıyor. İş parçacıkları pencereyle bir olay
     kuyruğu üzerinden konuşuyor.
   - HTTPS doğrulaması açık. Ağ isteklerinin zaman aşımı ve sınırlı
     yeniden deneme hakkı var.
   - Dosya adları benzersiz ve Windows'un yol sınırına sığıyor.
   - FFmpeg algılanıyor. FFmpeg eksikse açık bir hata gösteriliyor.
   - Bağımlılıklar sabitlendi ve derleme yeniden üretilebilir hale geldi.
     CI'de Windows ve Linux'ta 340'tan fazla test çalışıyor.
3. **Yeni tasarım, diller ve kurulum** (v1.0.0). Pencere yeniden
   tasarlandı ve ayarlar pencerenin içine taşındı. 25 dil ve GitHub
   Actions'ın derleyip test ettiği bir Windows kurulumu eklendi.
4. **TikTok** (v1.0.1). curl_cffi artık pakette, yt-dlp tarayıcı gibi
   istek gönderebiliyor.
5. **Windows düzeltmesi** (v1.0.2). Mod düğmeleri açılışta küçülmüyor.
6. **Android uygulaması.** İndirme kodunu Windows uygulamasıyla paylaşıyor.
   FFmpeg ve QuickJS Android için derlenip pakete eklendi. Her değişiklik
   CI'de bir Android emülatöründe test ediliyor.
7. **Android 0.2.** Bu sürümle gelenler:
   - Material You tasarımı;
   - ayarlar;
   - TikTok, kırpma ve Paylaş menüsü;
   - geçmiş;
   - daha hızlı indirme.
8. **Android kararlılığı.** Qualcomm Adreno grafik işlemcili telefonlarda
   (birçok Xiaomi ve Samsung) uygulama ilk dokunuşta kapanıyordu. Grafik
   sürücüsünü çökerten dokunma efekti kapatıldı. Hata raporları uygulamanın
   içinden kopyalanabiliyor.
9. **Telefonda YouTube.** YouTube "bot olmadığınızı doğrulayın" derse Orbida
   telefonun tarayıcı motoru üzerinden yeniden deniyor. Hesap gerekmiyor.
10. **Hız ve Orbida adı.** Listeler ve pencereler hafifledi. Uygulama yeni
    adını ve yörünge simgesini aldı.
11. **Orbida 1.0.** İki uygulama artık aynı ada, simgeye ve ayarlara sahip.
    Windows'a bu sürümle eklenenler:
    - Geçmiş sayfası;
    - vurgu renkleri;
    - paralel bağlantı;
    - otomatik yapıştırma;
    - indirme sürerken bilgisayarı uyanık tutma.

    İki uygulama da kendini güncelliyor. Android sürümleri projenin kendi
    anahtarıyla imzalanıyor ve iki uygulama tek bir sürümde yayınlanıyor.

Açık kalanlar: Windows için kod imzalama (sertifika gerekiyor), proxy
ayarları ve oynatma listesi seçiminin hatırlanması.

## Kaynaktan çalıştırma (Windows)

Python 3.11 veya üstü gerekir.

```
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements-dev.txt
git lfs pull            # gerçek bin\ffmpeg.exe ve bin\ffprobe.exe
python main.py
```

Denetimleri `python -m ruff check .` ve `python -m pytest` ile
çalıştırın. Ayrıntılar: [DEVELOPMENT.md](DEVELOPMENT.md).

## Derleme ve yayın

- `python build_app.py --onedir` uygulama klasörünü derler.
  `installer\Orbida.iss` (Inno Setup 6) onu kurulum dosyasına çevirir.
  Ayrıntılar: [docs/building.md](docs/building.md).
- Android APK'sı buildozer ile derlenir. Ayrıntılar:
  [android/README.md](android/README.md).
- **Release** iş akışı iki uygulamayı derler ve test eder:
  - Windows uygulamasını bir sunucuya kurar ve yerinde günceller.
  - Android uygulamasını emülatörde dener.

  Ardından iki dosyayı `orbida-v<sürüm>` etiketli tek bir sürümde
  yayınlar.

## Lisans notları

Uygulamalar, FFmpeg dahil, kendi lisanslarına tabi üçüncü taraf yazılımlar
içerir. Bkz. [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
