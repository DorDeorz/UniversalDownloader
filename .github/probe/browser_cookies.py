"""Temporary: visit YouTube anonymously in Chromium and save its cookies as a Netscape file."""
import sys

from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Linux; Android 13; 22111317PG) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/140.0.0.0 Mobile Safari/537.36")

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_context(user_agent=UA, locale="en-US").new_page()
    page.goto("https://m.youtube.com/", wait_until="load")
    page.wait_for_timeout(8000)
    page.goto("https://m.youtube.com/watch?v=dQw4w9WgXcQ", wait_until="load")
    page.wait_for_timeout(8000)
    cookies = page.context.cookies()
    print("page title:", page.title())
    browser.close()

lines = ["# Netscape HTTP Cookie File", ""]
for c in cookies:
    if "youtube.com" not in c["domain"]:
        continue
    domain = c["domain"] if c["domain"].startswith(".") else "." + c["domain"]
    lines.append("\t".join((domain, "TRUE", c["path"], "TRUE", str(int(c["expires"]) if c["expires"] > 0 else 2000000000),
                            c["name"], c["value"])))
    print("cookie", c["domain"], c["name"])
open(sys.argv[1], "w").write("\n".join(lines) + "\n")
