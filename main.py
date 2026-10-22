import os
import sys

import app_setup
from version import DISPLAY_NAME


def main():
    app_setup.configure_logging()
    app_setup.log_uncaught_errors()
    app_setup.use_downloaded_ytdlp()  # before ui imports yt_dlp
    app_setup.set_app_user_model_id()
    instance = app_setup.SingleInstance()
    # A link from the browser extension (orbida://download?url=...) or a command line.
    link = app_setup.link_from_args(sys.argv[1:])
    if instance.already_running:
        if app_setup.send_link(link or ""):
            return 0  # the running app takes the link, or just comes to the front
        from tkinter import Tk, messagebox
        root = Tk()
        root.withdraw()
        messagebox.showinfo(DISPLAY_NAME, "The app is already running.")
        root.destroy()
        return 0
    try:
        app_setup.migrate_legacy_data()
        from ui import App
        # The updater releases the instance lock before it starts the installer.
        app = App(instance=instance, link=link)
        # Release check: install this setup EXE the way the updater does
        # (see the "Update the running app" step in release.yml).
        test_installer = os.environ.pop("ORBIDA_SELFTEST_UPDATE", None)
        if test_installer:
            app.after(5000, app._on_update_ready, test_installer)
        app.mainloop()
    finally:
        instance.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
