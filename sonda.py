"""Sonda temporária (só no PR de testes): acha a API de busca/produto do Shopping do Inter."""
import re

from curl_cffi import requests

H = {"Accept-Language": "pt-BR,pt;q=0.9"}
BASE = "https://shopping.inter.co"


def get(url):
    r = requests.get(url, headers=H, timeout=30, impersonate="chrome")
    return r.status_code, r.text


st, home = get(BASE + "/")
manifesto = re.search(r'src="([^"]*_buildManifest\.js)"', home)
st, man = get(BASE + manifesto.group(1)) if manifesto else (0, "")
rotas = re.findall(r'"(/[^"]*)":\[([^\]]*)\]', man)
print("[sonda] rotas:", [r for r, _ in rotas][:80])

alvos = [r for r in rotas if "/p/" in r[0] or r[0] in ("/busca", "/[...slug]", "/[slug]")]
chunks = set()
for rota, lista in alvos:
    for c in re.findall(r'"(static/chunks/[^"]+\.js)"', lista):
        chunks.add(c)
    print("[sonda] rota", rota, "->", re.findall(r'"(static/chunks/[^"]+\.js)"', lista)[-2:])
# variáveis (c, s, a...) apontam para chunks comuns: pega todos os chunks citados no manifesto
for c in re.findall(r'"(static/chunks/[^"]+\.js)"', man):
    chunks.add(c)
scripts = re.findall(r'<script[^>]+src="([^"]+\.js)"', home)
urls = [BASE + "/_next/" + c for c in sorted(chunks)] + [s if s.startswith("http") else BASE + s for s in scripts]

caminhos, contextos = set(), []
for url in list(dict.fromkeys(urls))[:120]:
    try:
        st, js = get(url)
    except Exception:  # noqa: BLE001
        continue
    for m in re.finditer(r'/site/[A-Za-z0-9_\-/${}.]{2,70}', js):
        caminhos.add(m.group(0))
    for m in re.finditer(r'(?:search|busca|product|produto)[A-Za-z]*[`"\']?\s*[,:(]\s*[`"\'][^`"\']{0,90}', js):
        t = m.group(0)
        if ("/" in t or "api" in t.lower()) and len(contextos) < 40 and t not in contextos:
            contextos.append(t)
print("[sonda] caminhos /site/:", sorted(caminhos)[:80])
for t in contextos:
    print("[sonda] ctx:", repr(t[:200]))
