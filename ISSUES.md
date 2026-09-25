# UniversalDownloader — Bilinen Sorunlar

Bu dosya, projedeki kaynak kodun, build yapılandırmasının ve mevcut çalışma ortamının statik incelemesiyle tespit edilen sorunları içerir. Bulgular düzeltilmiş olarak işaretlenmemiştir; bu depoda geliştirme sırasında referans olarak kullanılmalıdır.

İnceleme kapsamı:

- `main.py`
- `ui.py`
- `logic.py`
- `utils.py`
- `build_app.py`
- `UniversalDownloader_v01.spec`
- `requirements.txt`
- `bin/ffmpeg.exe` ve `bin/ffprobe.exe`
- Mevcut `venv`, `build` ve `dist` artifact'ları

İnceleme yöntemi statik kod ve dosya analizidir. Uzak bir video indirilerek uygulamanın canlı ağ davranışı doğrulanmamıştır.

## Kritik sorunlar

1. **[KRİTİK] Kırpma özelliği çalışmıyor.** `ui.py:243-247` timestamp metnini oluşturuyor; `logic.py:105-112` ise bunu yt-dlp `download_range_func` fonksiyonuna string listesi olarak veriyor. Kurulu yt-dlp API'si başlangıç ve bitiş değerlerini `(start, end)` tuple biçiminde bekliyor. `0 <= start < end <= duration` doğrulaması da yok.
2. **[KRİTİK] TLS sertifika doğrulaması kapatılmış.** `logic.py:52-59` içindeki `nocheckcertificate=True`, HTTPS indirmelerinde MITM ve sahte sunucu riski oluşturuyor.
3. **[KRİTİK] Worker thread'lerinden doğrudan Tkinter widget'ları güncelleniyor.** `ui.py:168-230` içinde log, buton, progress bar ve messagebox işlemleri worker thread'lerinden yapılıyor. Bu, UI donması, yarış condition'ı ve kapanış hatalarına yol açabilir.
4. **[KRİTİK] Başarısız indirmeler "FINISHED" olarak gösteriliyor.** `logic.py:114-128` gerçek başarı sonucu döndürmüyor; `ui.py:212-222` ise her durumda `FINISHED`, `Complete` ve `Finished!` gösteriyor.
5. **[KRİTİK] Hatalar sessizce yutuluyor.** `ignoreerrors=True`, `quiet=True` ve `no_warnings=True` ayarları metadata, medya ve postprocessor hatalarını gizliyor.
6. **[KRİTİK] Video Only seçeneği uygulanmıyor.** `logic.py:66-93` içinde `Video Only` ve `Video + Audio` seçenekleri aynı `else` format mantığını kullanıyor; sesli video indirilebiliyor.
7. **[KRİTİK] Audio Only format listesi hatalı.** `ui.py:128-136` video container'larını ses codec'i olarak sunuyor; `mp4`, `mkv` ve `avi` değerleri `preferredcodec` olarak kullanılamaz.
8. **[KRİTİK] Audio Only varsayılanı geçersiz.** Varsayılan `mp4` seçimi `logic.py:74` üzerinden FFmpegExtractAudio'ya geçiriliyor ve codec lookup hatası oluşturabilir.
9. **[KRİTİK] AAC dosya uzantısı yanlış.** yt-dlp AAC çıktısını genellikle `.m4a` üretir; `logic.py:119-122` kullanıcı seçiminden `.aac` dosya adı üretiyor.
10. **[KRİTİK] Video container seçimi garanti edilmiyor.** `merge_output_format` yalnızca postprocessor tercihidir; uyumsuz codec veya container için istenen sonuç oluşmayabilir.
11. **[YÜKSEK] Kalite sınırı atlanabiliyor.** `logic.py:86-95` içindeki `/best` fallback'i, kullanıcı 720p veya 1080p seçse bile daha yüksek çözünürlük seçebiliyor.
12. **[YÜKSEK] Audio modunda kalite seçeneği gösteriliyor ama kullanılmıyor.** `ui.py:134-136` seçeneği gösteriyor, `logic.py:68-83` audio akışında dikkate almıyor.
13. **[YÜKSEK] Uygulama seviyesinde timeout, retry ve iptal politikası yok.** `logic.py:27-32` ve `ui.py:168-222` kalıcı bağlantı veya uzun süren hatalar için kontrol sağlamıyor.
14. **[YÜKSEK] Worker thread yaşam döngüsü yönetilmiyor.** Thread referansları saklanmıyor, `join()` ve kontrollü kapanış protokolü yok; non-daemon thread'ler kapanışı geciktirebilir.
15. **[YÜKSEK] Eşzamanlı analiz ve indirme engeli yok.** Kullanıcı ikinci iş başlattığında farklı worker'lar aynı UI durumunu ve queue'u bozabilir.

## Playlist, metadata ve durum sorunları

16. **Playlist girdileri gerçek indirilebilirlik açısından doğrulanmıyor.** `ui.py:43-70` yalnızca başlık ve URL topluyor; gizli, silinmiş veya erişilemeyen videolar queue'a girebilir.
17. **“Oynatılabilir video” sayımı güvenilir değil.** `extract_flat` çıktısındaki her sözlük gerçekten oynatılabilir kabul ediliyor.
18. **`entries=None` durumunda çökme riski var.** `ui.py:183-185` playlist girdilerini doğrudan listeye çeviriyor.
19. **Playlist seçimi yalnızca URL ve başlığa indirgeniyor.** Format, süre, codec, erişilebilirlik ve tahmini boyut bilgileri taşınmıyor.
20. **Playlist seçimi kalıcı değil.** Uygulama yeniden açıldığında seçimler kayboluyor.
21. **Playlist penceresi tam modal değil.** `grab_set()` kullanılıyor fakat `transient()`, `wait_window()` ve iptal sonucu yok.
22. **Playlist penceresi kapatılırsa kullanıcı kararı uygulanmıyor.** Kapatma ile iptal arasında ayrım bulunmuyor.
23. **Büyük playlist'lerde arayüz donabilir.** Her video için ayrı widget oluşturuluyor; sanal liste veya sayfalama yok.
24. **Boş playlist onaylanabiliyor.** Boş queue ile işlem başlatılabiliyor.
25. **Playlist indirmeleri aynı videoları tekrar tekrar metadata isteğiyle inceliyor.** Her seçilen öğe için `fetch_info()` yeniden çalışıyor (`ui.py:212-221`, `logic.py:46-128`).
26. **Metadata hataları yalnızca metne dönüştürülüyor.** `logic.py:34-44` exception türünü korumuyor; ağ, extractor ve format hataları ayırt edilemiyor.
27. **Eski queue yeni URL girildiğinde temizlenmiyor.** Eski analiz sonuçları yanlış indirmeye yol açabilir.
28. **Queue çalışırken değiştirilebiliyor.** Worker, işlenen listede değişiklik olursa tutarsız sonuç verebilir.
29. **Durum modeli merkezi değil.** URL, format, kalite, queue, ilerleme ve buton durumları farklı widget ve manager alanlarına dağılmış.
30. **Yeni iş başlatıldığında önceki ilerleme değeri temizlenmiyor.** Eski yüzde yeni işin başlangıcında kalabiliyor.
31. **Kısmi başarı, atlanan öğe ve iptal durumları ayrılmıyor.** Playlist sonunda hangi videoların başarısız olduğu bilinmiyor.
32. **URL doğrulaması yok.** Geçersiz veya desteklenmeyen URL'ler ağ isteği başlatabiliyor.
33. **Log ve hata modeli yetersiz.** Hatalar yalnızca genel mesajlara dönüşüyor; hangi dosya veya aşamanın başarısız olduğu görünmüyor.

## Dosya çıktısı ve kullanıcı deneyimi sorunları

34. **Dosya adı çakışmaları mümkün.** Çıktı şablonu yalnızca `%(title)s.%(ext)s` (`logic.py:47-49`); aynı başlığa sahip videolar üst üste yazılabiliyor.
35. **Overwrite politikası tanımlı değil.** Var olan dosya, yeni indirme, atlayırma veya numaralandırma davranışı belirlenmemiş.
36. **Playlist sırası dosya adına yansımıyor.** İkinci video ile üçüncü video karışabiliyor.
37. **Uzun ve uyumsuz dosya adları için uygulama seviyesinde kontrol yok.** Windows yol sınırı ve özel karakterler yt-dlp'ye bırakılmış.
38. **Platform algılaması URL metnine göre yapılıyor.** `logic.py:10-20`; kısa URL'ler, `youtu.be`, `t.co` ve yanlış eşleşen siteler yanlış klasöre gidebilir.
39. **Varsayılan indirme klasörü gerçek Windows Downloads klasörünü garanti etmiyor.** `ui.py:92` doğrudan `~/Downloads` kullanıyor; OneDrive yönlendirmeleri ve özel konumlar hesaba katılmıyor.
40. **Hedef klasörün yazılabilirliği başlangıçta kontrol edilmiyor.**
41. **Disk alanı ve indirme öncesi kapasite kontrolü yok.**
42. **`.part` ve postprocessor geçici dosyalarının temizlik politikası yok.**
43. **Ayar ve geçmiş kalıcı değil.** Tema, klasör, format, kalite, trim ve son işlemler yeniden başlatmada kayboluyor.
44. **Sabit pencere boyutları kullanılıyor.** `ui.py:16`, `ui.py:77-79`; yüksek DPI veya düşük çözünürlükte taşma riski var.
45. **Playlist ve ana pencere kapatılırken worker durumu koordinasyonu yok.**
46. **Tek bir uygulama örneğini sınırlayan mutex yok.** Aynı klasöre eşzamanlı iki indirme çakışabilir.

## FFmpeg ve medya işleme sorunları

47. **FFmpeg/ffprobe varlığı başlangıçta doğrulanmıyor.**
48. **FFmpeg çalıştırılabilirliği ve sürümü build sırasında doğrulanmıyor.**
49. **ffprobe yolu hesaplanıyor ama doğrudan kullanılmıyor.** `utils.py:14-20`; yt-dlp kardeş dosyayı bulabilse de bu durum açıkça doğrulanmıyor.
50. **Postprocessor aşamaları ilerleme modeline dahil edilmiyor.** Merge, thumbnail, metadata ve ses dönüşümü sırasında UI doğru ilerleme göstermiyor.
51. **Postprocessor hataları başarı sonucuna yansımıyor.**
52. **Dosya oluştuğu veya boş olmadığı doğrulanmıyor.** Başarılı görünen bir işlem çıktı üretmemiş olabilir.
53. **Ses formatı seçimi codec, container ve uzantı olarak birbirine karıştırılmış.**
54. **Ses seçilen içerikte ses akışı yoksa davranış net değil.**
55. **Formatların gerçekten mevcut olduğu önceden kontrol edilmiyor.**

## Bağımlılık, ortam ve build sorunları

56. **Bağımlılık sürümleri sabitlenmemiş.** `requirements.txt:1-5`; aynı kaynak farklı ortamlarda farklı davranabilir.
57. **yt-dlp'nin önerilen opsiyonel bağımlılıkları eksik.** `requests`, `certifi`, `mutagen`, `websockets`, `brotli`, `pycryptodomex` ve EJS paketleri kurulmamış.
58. **YouTube için JavaScript runtime/EJS desteği yok.** `yt-dlp-ejs` ve Deno/Node/Bun/QuickJS bulunmuyor; bazı YouTube formatları ve challenge akışları sorunlanabilir.
59. **`ffmpeg-python` bağımlılığı kodda kullanılmıyor.** `Pillow` da uygulama kodunda doğrudan kullanılmıyor.
60. **Eski ve taşınmış venv kullanılıyor.** `venv` içindeki activation scriptleri eski proje yolunu gösteriyor.
61. **Build çıktısı global site-packages kullanmış.** Mevcut build ağacı, venv dışındaki paketleri içeriyor; temiz ve tekrarlanabilir build değil.
62. **Venv Python sürümü ile `pyvenv.cfg` bilgisi uyuşmuyor.** Python 3.13.13 çalışma zamanına karşı 3.13.11 yapılandırması mevcut.
63. **`build_app.py` ve `.spec` farklı paketleme kuralları uyguluyor.** UPX, isimlendirme ve toplama davranışları farklı.
64. **Build script'i yalnızca `UniversalDownloader_vNN` dosyalarını sürümlendiriyor.** `FinalVideoIndirici.exe` ve `VideoIndirici_Final*.exe` dosyalarını yok sayıyor.
65. **Sürüm isimlendirmesi tutarsız.** `main.py:8` içindeki sürüm, build scriptindeki sürüm ve mevcut EXE isimleri birbiriyle eşleşmiyor.
66. **Build script'i FFmpeg, ffprobe ve ikon dosyalarının varlığını önceden doğrulamıyor.**
67. **Onefile paketleme yaklaşık 200 MB geçici dosya çıkarabiliyor.** Büyük FFmpeg dosyaları her açılışta geçici klasöre kopyalanıyor.
68. **Onefile kullanımı yavaş açılış, AV uyarıları ve SmartScreen problemleri oluşturabilir.**
69. **`app.ico` gerçek ICO değil, PNG dosyası.** Tkinter `iconbitmap()` kullanımı sessizce başarısız olabilir.
70. **`dist` içindeki EXE'lerin hangi kaynak sürümünden üretildiği doğrulanamıyor.** Mevcut dosya adları, tarihleri ve build yolları tutarsız.
71. **Kod imzalama yok.** EXE'ler ve FFmpeg dosyaları Authenticode ile imzalı değil.
72. **Release checksum veya manifest dosyası yok.**
73. **FFmpeg ve diğer üçüncü taraf lisanslarının dağıtım belgeleri eksik.** FFmpeg GPL yapısı özellikle ayrıca ele alınmalı.
74. **Otomatik test altyapısı yok.** Unit, UI, integration veya smoke test bulunmuyor.
75. **Lint ve typecheck yapılandırması yok.**
76. **CI/CD yapılandırması yok.**
77. **Build kaynağı ile release arasında izlenebilirlik yok.** Git commit, kaynak snapshot'ı veya sürüm manifesti bulunmuyor.
78. **Uygulama yalnızca Windows x64 varsayıyor.** `ctypes.windll`, `.exe` yolları ve FFmpeg dosyaları diğer platformları desteklemiyor.
79. **Başka çalışma dizininden başlatıldığında kaynak yolları bozulabilir.** `utils.py:4-12` CWD'ye bağlı çalışıyor; `__file__` kullanmıyor.
80. **Kullanılmayan import, değişken ve dosyalar var.** `resim.png`, `ffprobe_path`, `lbl_status` ve bazı importlar işlevsel olarak kullanılmıyor.
81. **Uygulama logları kalıcı ve yapılandırılmış değil.** Hata ayıklama yalnızca basit UI log satırlarına dayanıyor.
82. **Cache ve gizlilik davranışı kullanıcıya açıklanmıyor.** yt-dlp cache oluşturabiliyor; URL veya token bilgisi hata mesajlarına sızabiliyor.
83. **Proxy, özel CA, client certificate ve gelişmiş ağ ayarları yok.**
84. **Kullanıcıdan alınan URL'lerde gizlilik ve kötüye kullanım politikası yok.**
85. **Uygulama kapanırken aktif indirme için kullanıcı onayı ve iptal ekranı yok.**
86. **Başarılı, başarısız, iptal edilen ve atlanan görevlerin sonuç raporu yok.**
87. **Playlist sonunda dosya bazlı sonuç listesi gösterilmiyor.**
88. **Retry butonu veya hatalı öğeleri yeniden indirme özelliği yok.**
89. **İndirme sırasında oluşan dosya adı değişiklikleri kullanıcıya gösterilmiyor.**
90. **Format seçimi gerçek seçilen codec, container ve çözünürlük bilgisiyle doğrulanmıyor.**

## Önerilen düzeltme sırası

1. Worker thread'leri yalnızca veri üretecek şekilde değiştirip UI güncellemelerini ana thread'deki event queue üzerinden yapmak.
2. Trim aralıklarını sayısal `(start, end)` değerlerine dönüştürüp süre doğrulaması eklemek.
3. `nocheckcertificate=True` ayarını kaldırmak.
4. Video Only, Video + Audio ve Audio Only format sözleşmelerini ayırmak.
5. İndirme sonuçlarını completed, failed, cancelled ve skipped olarak modellemek.
6. Timeout, retry, iptal ve kontrollü kapanış eklemek.
7. Playlist doğrulama, dosya adı çakışma politikası ve ayar kalıcılığı eklemek.
8. FFmpeg/ffprobe build doğrulaması ve temiz, tekrarlanabilir build ortamı kurmak.
9. yt-dlp default/EJS bağımlılıklarını ve uygun JavaScript runtime desteğini doğrulamak.
10. Test, lint, typecheck, CI, release manifesti ve üçüncü taraf lisans belgelerini eklemek.

## Depoya eklenen geliştirme dosyaları

Bu depoya geliştirme için gerekli kaynaklar, build scriptleri, requirements, `bin` altındaki FFmpeg araçları ve bu sorun raporu eklenir. `venv/`, `build/` ve `dist/` yeniden üretilebilen yerel çıktılar olduğu için Git geçmişine alınmaz.
