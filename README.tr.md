# Universal Video Downloader

YouTube, TikTok, Instagram, X ve [yt-dlp](https://github.com/yt-dlp/yt-dlp)'nin
desteklediği diğer sitelerden video ve ses indiren bir Windows masaüstü
uygulaması. Python ve CustomTkinter ile yazıldı; birleştirme, dönüştürme ve
kırpma için FFmpeg kullanıyor.

[English](README.md)

![Ana pencere](docs/images/main-window.png)

## Kurulum

[Son sürümden](https://github.com/DorDeorz/UniversalDownloader/releases/latest)
**UniversalDownloader-Setup-&lt;sürüm&gt;.exe** dosyasını indirip çalıştırın.
Kurulum programı uygulamanın ihtiyaç duyduğu her şeyi içeriyor: uygulamanın
kendisi, FFmpeg ve ffprobe, ayrıca yt-dlp'nin YouTube için kullandığı Deno.
Yönetici izni istemeden yalnızca sizin kullanıcınıza kurulur ve Başlat
menüsüne eklenir. Windows 10 veya 11 (64 bit) gerekir.

Kurulum programı kod imzalı olmadığı için Windows SmartScreen "Windows
bilgisayarınızı korudu" uyarısı gösterebilir. **Ek bilgi**'ye, ardından
**Yine de çalıştır**'a tıklayın.

## Neler yapıyor

- **Bağlantıyı yapıştırıp analiz edin.** Uygulama bağlantıda ne olduğunu
  gösterir: süresiyle bir video ya da kaç öğesi indirilebilen bir oynatma
  listesi. Özel, silinmiş, yalnızca üyelere açık ve canlı yayın öğeleri,
  neden atlandıklarıyla birlikte listelenir.
- **Neyin kaydedileceğini seçin.**
  - Video + Ses, Yalnızca video veya Yalnızca ses.
  - Bir video biçimi (mp4, mkv veya webm) ya da bir ses biçimi (mp3, m4a,
    opus, flac veya wav).
  - Bir kalite sınırı (4K'dan 360p'ye) ya da bir ses bit hızı.
  - Videonun yalnızca bir kısmı (ör. 0:10 ile 1:30 arası).
- **Her sonucu görün.** Her öğe tamamlandı, başarısız, atlandı ya da iptal
  edildi olarak biter; tamamlanmadıysa nedeni de yazılır. Başarısız öğeler
  tek tıkla yeniden denenebilir. Süren bir indirme, yarım dosya bırakmadan
  iptal edilebilir.
- **Dosyalar birbirinin üzerine yazılmaz.** İkinci bir "Başlık.mp4",
  "Başlık (2).mp4" olur. Oynatma listeleri numaralı adlarla kendi
  klasörlerine iner.
- **Ayarlar.** Ayarlar pencerenin içinde açılır:
  - 25 dil.
  - Koyu, açık ya da sistem teması.
  - Üç metin boyutu.
  - İndirmeler bitince ne olacağı.
  - Klavye kısayolları: Enter analiz eder, Ctrl+Enter indirir, Esc iptal
    eder.
  - Seçimler uygulama kapatılıp açılınca hatırlanır.

![Ayarlar](docs/images/settings.png)

## Nasıl başladı, şimdi ne durumda

Proje, dört dosyada (`main.py`, `ui.py`, `logic.py` ve `utils.py`) yaklaşık
400 satırlık çalışan bir prototip olarak başladı. Bu kodun incelemesi
[ISSUES.md](ISSUES.md) dosyasına yazıldı ve 90 sorun buldu. Başlıcaları:

- **Çalışmayan özellikler.** Kırpma çöküyordu. Yalnızca video seçeneği sesi
  de indiriyordu. Yalnızca ses seçeneği mp4 gibi video biçimlerini ses
  biçimi olarak sunuyordu.
- **Güvenlik ve sessiz hatalar.** HTTPS sertifika denetimi kapalıydı ve
  hatalar gizleniyordu. Hiçbir şey inmese bile her iş "Finished!" ile
  bitiyordu.
- **İş parçacıkları.** Arka plan iş parçacıkları pencereyi doğrudan
  güncelliyordu; bu, pencerenin donmasına ya da çökmesine yol açabiliyordu.
  Aynı anda iki indirme çalışabiliyordu.
- **Dosyalar.** Aynı başlıklı dosyalar birbirinin üzerine yazılıyordu.
- **Kurulum ve derleme.** FFmpeg dosyaları Git LFS işaretçisi olduğu için
  depodan doğrudan indirilen kopya FFmpeg olmadan açılıyor ve ilk
  indirmede hata veriyordu. Test yoktu, bağımlılıkların sürümleri
  sabitlenmemişti ve derleme tekrarlanabilir değildi.
- **Pencere.** Pencerenin boyutu sabitti ve hiçbir seçimi hatırlamıyordu.

Düzeltmeler özgün yapıyı korudu: pencere için `ui.py`, yt-dlp için
`logic.py`. Bunların etrafında büyüyen kod küçük modüllere taşındı; her biri
[`docs/`](docs) klasöründe anlatılıyor:

| Alan | Şimdi |
|---|---|
| Doğruluk | Her mod söylediğini üretiyor: gerçek ses kodekleri, kesin kalite sınırı, seçilen biçim; kodek uymazsa yeniden kodlama. Kırpma, paketlenmiş uygulamada da çalışıyor. |
| Güvenlik | HTTPS denetimi açık, hatalar anlaşılır sözlerle gösteriliyor, ağ zaman aşımları ve sınırlı yeniden denemeler var, bağlantılar istek atılmadan önce denetleniyor. |
| Güvenilirlik | Aynı anda tek iş; iş parçacıkları pencereyle bir olay kuyruğu üzerinden konuşuyor; iptal ve kapatma temiz; uygulamanın ikinci kopyası açılmıyor. |
| Dosyalar | Benzersiz adlar, Windows yol sınırına uyan uzunluklar, oynatma listesi klasörleri, indirmeden önce yazma izni ve disk alanı denetimi. |
| Pencere | Her metin boyutunda ekrana (ve görev çubuğunun üstüne) sığan, yeniden tasarlanmış, boyutu değiştirilebilen pencere; tek ekrana sığan uygulama içi ayarlar; iki temada WCAG AA metin kontrastı. |
| Diller | Canlı değiştirilebilen 25 dil; eksik metinlerde İngilizce kullanılıyor (`locales/`). |
| Testler | CI'da Windows ve Linux'ta 340'tan fazla test; buna yerel bir sunucuya karşı gerçek yt-dlp ve FFmpeg indirmeleri de dahil (internet gerekmez). |
| Derleme | Sabit sürümlü bağımlılıklar, tek PyInstaller tanımı, bozuk derlemeyi reddeden ön denetim, sağlama toplamları ve derleme bilgisi, GitHub Actions'ta derlenip denenen bir Windows kurulum programı. |

ISSUES.md'deki birkaç madde bir karar ya da dış bir kaynak gerektirdiği için
hâlâ açık: kod imzalama, proxy ayarları ve oynatma listesi seçiminin
kaydedilmesi. Bunlar
[pull request](https://github.com/DorDeorz/UniversalDownloader/pull/5)
açıklamasında listeleniyor.

## Kaynaktan çalıştırma

Python 3.11 veya daha yenisi gerekir.

```
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements-dev.txt
git lfs pull            # gerçek bin\ffmpeg.exe ve bin\ffprobe.exe
python main.py
```

Denetimler: `python -m ruff check .` ve `python -m pytest`. Ayrıntılar
[DEVELOPMENT.md](DEVELOPMENT.md) dosyasında.

## Derleme

- `python build_app.py` tek, taşınabilir bir EXE derler.
- `python build_app.py --onedir` bir klasör derler;
  `installer\UniversalDownloader.iss` (Inno Setup 6) bunu kurulum EXE'sine
  dönüştürür.
- GitHub'daki **Release** iş akışı ikisini de yapar. Sonucu bir Windows
  makinesine kurar, uygulamayı başlatır, kaldırır ve ardından sürümü
  yayınlar.

Ayrıntılar [docs/building.md](docs/building.md) dosyasında.

## Lisans notları

Uygulama, FFmpeg dahil kendi lisanslarına sahip üçüncü taraf yazılımlar
içeriyor. Bkz. [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
