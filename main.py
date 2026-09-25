import sys

import app_setup


def main():
    app_setup.configure_logging()
    app_setup.set_app_user_model_id()
    instance = app_setup.SingleInstance()
    if instance.already_running:
        from tkinter import Tk, messagebox
        root = Tk()
        root.withdraw()
        messagebox.showinfo("Universal Video Downloader", "The app is already running.")
        root.destroy()
        return 0
    try:
        from ui import App
        app = App()
        app.mainloop()
    finally:
        instance.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
