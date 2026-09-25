"""Serve a folder over HTTP with byte ranges, like a real media server.

The emulator test downloads its sample video from this server. FFmpeg
reads the URL itself for trimmed downloads and seeks with Range requests;
Python's plain ``http.server`` ignores them, and FFmpeg then fails with
"invalid data" (exit code 183). Real video hosts all support ranges.

    python android/range_server.py <folder> [port]
"""

import http.server
import os
import sys


class RangeHandler(http.server.SimpleHTTPRequestHandler):
    def send_head(self):
        self._range = None
        header = self.headers.get("Range", "")
        path = self.translate_path(self.path)
        if not header.startswith("bytes=") or not os.path.isfile(path):
            return super().send_head()
        size = os.path.getsize(path)
        first, _, last = header[len("bytes="):].split(",")[0].partition("-")
        if first:
            start, end = int(first), int(last) if last else size - 1
        else:
            start, end = max(size - int(last), 0), size - 1
        end = min(end, size - 1)
        if start >= size or start > end:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return None
        f = open(path, "rb")
        f.seek(start)
        self._range = end - start + 1
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(self._range))
        self.end_headers()
        return f

    def copyfile(self, source, outputfile):
        remaining = self._range
        while chunk := source.read(64 * 1024 if remaining is None else min(64 * 1024, remaining)):
            if remaining is not None:
                remaining -= len(chunk)
            try:
                outputfile.write(chunk)
            except OSError:
                return


def main(folder, port=8000):
    os.chdir(folder)
    http.server.ThreadingHTTPServer(("", port), RangeHandler).serve_forever()


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 8000)
