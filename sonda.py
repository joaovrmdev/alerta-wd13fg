"""Sonda temporária (só no PR de testes): rota de produto e API de busca do Shopping do Inter."""
import re

from curl_cffi import requests

H = {"Accept-Language": "pt-BR,pt;q=0.9"}
BASE = "https://shopping.inter.co"


def get(url):
    r = requests.get(url, headers=H, timeout=30, impersonate="chrome", allow_redirects=True)
    return r.status_code, r.text, str(r.url)


for caminho in ("/Tenis-Olympikus-Delta/p/13045947?v=15988679", "/x/p/13045947?v=15988679", "/x/p/13045947",
                "/x/p/11956898", "/x/p/11956898?v=14851930", "/x/r/11956898", "/x/dp/11956898"):
    st, txt, final = get(BASE + caminho)
    nome = re.search(r"<title[^>]*>(.*?)</title>", txt, re.S)
    print(f"[sonda] {caminho} -> {st} {final} title={nome.group(1)[:90] if nome else None!r}")

st, home, _ = get(BASE + "/")
scripts = [s if s.startswith("http") else BASE + s for s in re.findall(r'<script[^>]+src="([^"]+\.js)"', home)]
scripts += [BASE + "/_next/static/chunks/5910-0ce95d8d259ccbab.js", BASE + "/_next/static/chunks/9332-2f75c391b5a51433.js",
            BASE + "/_next/static/chunks/8035-424e51ac4e95edbc.js"]
vistos = set()
for url in dict.fromkeys(scripts):
    st, js, _ = get(url)
    print(f"[sonda] js {url.split('/')[-1][:45]} {st} {len(js)}")
    for m in re.finditer(r"marketplace-api[^\"'`]{0,60}|[\"'`]/(?:site|api|v\d)/[^\"'`]{2,80}", js):
        t = js[max(0, m.start() - 80): m.end() + 60].replace("\n", " ")
        chave = m.group(0)[:50]
        if chave not in vistos:
            vistos.add(chave)
            print(f"[sonda]   {t[:260]!r}")
