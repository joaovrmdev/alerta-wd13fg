"""Sonda temporária (só no PR de testes): descobre como o Shopping do Inter monta busca e links de produto."""
import json
import re

from curl_cffi import requests

H = {"Accept-Language": "pt-BR,pt;q=0.9"}
BASE = "https://shopping.inter.co"


def get(url):
    r = requests.get(url, headers=H, timeout=30, impersonate="chrome")
    return r.status_code, r.text


st, home = get(BASE + "/")
print("home", st, len(home))
for padrao in (r'href="([^"]*/p/[^"]*)"', r'href="([^"]*/c/[^"]*)"', r'"url":"([^"]{3,120})"'):
    achados = list(dict.fromkeys(re.findall(padrao, home)))[:12]
    print(f"[sonda] {padrao}: {achados}")

st, busca = get(BASE + "/busca?search=wd13fg")
m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', busca, re.S)
if m:
    d = json.loads(m.group(1))
    print("[sonda] busca page:", d.get("page"), "query:", d.get("query"), "buildId:", d.get("buildId"))
    print("[sonda] pageProps keys:", list((d.get("props") or {}).get("pageProps", {}).keys())[:30])
else:
    print("[sonda] busca sem __NEXT_DATA__")

scripts = list(dict.fromkeys(re.findall(r'<script[^>]+src="([^"]+\.js)"', busca)))
print(f"[sonda] {len(scripts)} scripts")
vistos = set()
for src in scripts[:60]:
    url = src if src.startswith("http") else BASE + src
    try:
        st, js = get(url)
    except Exception as e:  # noqa: BLE001
        print("[sonda] erro", url, e)
        continue
    for padrao in (r'.{0,90}/busca.{0,120}', r'.{0,60}(?:search|busca)[A-Za-z]*\?.{0,80}',
                   r'https://[a-z0-9.-]*inter[a-z0-9.-]*/[^"\'` ]{0,80}'):
        for trecho in re.findall(padrao, js)[:6]:
            t = trecho.strip()
            if t not in vistos and len(vistos) < 60:
                vistos.add(t)
                print(f"[sonda] {src.split('/')[-1][:40]} :: {t[:230]!r}")
