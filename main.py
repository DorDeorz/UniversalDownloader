import ctypes
from ui import App

# --- 1. UYGULAMA KİMLİĞİNİ TANIMLA (APP ID) ---
# Bu, görev çubuğunda ikonun doğru gruplanmasını sağlar.
myappid = 'uvd.downloader.pro.v7' 
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
except ImportError:
    pass
# ---------------------------------------------

if __name__ == "__main__":
    # Uygulamayı başlat
    app = App()
    app.mainloop()