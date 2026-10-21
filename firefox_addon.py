"""The Mozilla-signed Firefox add-on (release workflow helper, standard library only).

Firefox keeps only add-ons that Mozilla signed. The release workflow has
browser_extension/ signed on addons.mozilla.org (AMO) in the unlisted channel
(signed for self-distribution, no store page) with ``web-ext sign``, then the
installer ships the file as firefox/Orbida.xpi.

AMO signs each version number once. So that a release run can run again,
``fetch`` first downloads the copy AMO already signed for this version:

    python firefox_addon.py fetch firefox/Orbida.xpi   # exit 2: not signed yet
    python firefox_addon.py check firefox/Orbida.xpi   # signed, this version, same files

Both read the AMO API key from AMO_JWT_ISSUER and AMO_JWT_SECRET
(addons.mozilla.org > Developer Hub > Manage API Keys).
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
import zipfile

from version import __version__

ROOT = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(ROOT, "browser_extension")
API = "https://addons.mozilla.org/api/v5"
NOT_SIGNED = 2  # exit code of ``fetch`` when AMO has no such version yet
# Files Mozilla's signature adds (cose.* is the newer signature, mozilla.* the older one).
SIGNATURE_FILES = ("META-INF/manifest.mf", "META-INF/mozilla.rsa", "META-INF/mozilla.sf")


def addon_id(source=SOURCE):
    with open(os.path.join(source, "manifest.json"), encoding="utf-8") as f:
        return json.load(f)["browser_specific_settings"]["gecko"]["id"]


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def jwt_token(issuer, secret, now=None):
    """The HS256 token AMO wants in "Authorization: JWT <token>" (valid one minute)."""
    issued = int(time.time() if now is None else now)
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64(json.dumps({"iss": issuer, "jti": secrets.token_hex(16), "iat": issued, "exp": issued + 60},
                              separators=(",", ":")).encode())
    signature = hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64(signature)}"


def _get(url, issuer, secret, opener=urllib.request.urlopen):
    request = urllib.request.Request(url, headers={"Authorization": "JWT " + jwt_token(issuer, secret),
                                                   "User-Agent": "Orbida release workflow"})
    with opener(request, timeout=60) as response:
        return response.read()


def signed_file_url(guid, version, issuer, secret, opener=urllib.request.urlopen):
    """Download address of the signed file AMO has for ``version``, or None when it has none.

    Raises RuntimeError when the version exists but is not signed (yet).
    """
    # The "v" prefix makes AMO read the number as a version, not a version id.
    url = f"{API}/addons/addon/{guid}/versions/v{version}/"
    try:
        info = json.loads(_get(url, issuer, secret, opener))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise RuntimeError(f"AMO refused the API key (HTTP {e.code}): check AMO_JWT_ISSUER and AMO_JWT_SECRET")
        if e.code == 404:  # no such version, or no such add-on yet
            return None
        raise
    file = info.get("file") or {}
    if file.get("status") != "public":
        raise RuntimeError(f"AMO has version {version} but it is not signed (status {file.get('status')!r}); "
                           "see the add-on's page in the AMO Developer Hub")
    return file["url"]


def fetch(target, issuer, secret, version=__version__, source=SOURCE, opener=urllib.request.urlopen):
    """Save the signed copy of ``version`` to ``target``; False when AMO has none yet."""
    url = signed_file_url(addon_id(source), version, issuer, secret, opener)
    if url is None:
        return False
    data = _get(url, issuer, secret, opener)
    os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
    with open(target, "wb") as f:
        f.write(data)
    return True


def check(path, version=__version__, source=SOURCE):
    """Problems with the signed add-on at ``path`` (empty when it is fine to ship)."""
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as e:
        return [f"{path} is not an add-on file: {e}"]
    problems = []
    with archive:
        names = set(archive.namelist())
        if not set(SIGNATURE_FILES) <= names and "META-INF/cose.sig" not in names:
            problems.append(f"{path} is not signed by Mozilla")
        try:
            manifest = json.loads(archive.read("manifest.json"))
        except (KeyError, ValueError):
            return problems + [f"{path} has no readable manifest.json"]
        if manifest.get("version") != version:
            problems.append(f"{path} is version {manifest.get('version')}, the app is {version}")
        # A version signed earlier with other files: AMO will not sign the number again.
        for folder, _dirs, files in os.walk(source):
            for name in files:
                full = os.path.join(folder, name)
                inside = os.path.relpath(full, source).replace(os.sep, "/")
                with open(full, "rb") as f:
                    ours = f.read()
                if inside not in names or archive.read(inside) != ours:
                    problems.append(f"{inside} differs from the signed add-on: raise the version in version.py "
                                    "and browser_extension/manifest.json")
    return problems


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2 or argv[0] not in ("fetch", "check"):
        print(__doc__)
        return 1
    command, path = argv
    if command == "check":
        problems = check(path)
        for problem in problems:
            print(f"::error::{problem}")
        if not problems:
            print(f"{path}: signed by Mozilla, version {__version__}, same files as browser_extension/")
        return 1 if problems else 0
    issuer, secret = os.environ.get("AMO_JWT_ISSUER"), os.environ.get("AMO_JWT_SECRET")
    if not issuer or not secret:
        print("::error::AMO_JWT_ISSUER and AMO_JWT_SECRET are not set")
        return 1
    try:
        found = fetch(path, issuer, secret)
    except (RuntimeError, OSError) as e:
        print(f"::error::{e}")
        return 1
    print(f"Downloaded the signed version {__version__} to {path}" if found
          else f"AMO has no signed version {__version__} yet")
    return 0 if found else NOT_SIGNED


if __name__ == "__main__":
    sys.exit(main())
