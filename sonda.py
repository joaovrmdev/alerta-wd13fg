"""Sonda temporária (só no PR de testes): API de busca do Shopping do Inter."""
import re

from curl_cffi import requests

H = {"Accept-Language": "pt-BR,pt;q=0.9", "Accept": "application/json, text/plain, */*",
     "Origin": "https://shopping.inter.co", "Referer": "https://shopping.inter.co/"}
API = "https://marketplace-api.web.bancointer.com.br/site/affiliate/inter"


def get(url, **kw):
    r = requests.get(url, headers={**H, **kw.pop("headers", {})}, timeout=30, impersonate="chrome", **kw)
    return r.status_code, r.text


st, js = get("https://shopping.inter.co/_next/static/chunks/636-252ea0c232785f0e.js")
m = re.search(r"YF:\(\)=>(\w+)", js)
if m:
    var = m.group(1)
    d = re.search(r"[,; ]" + re.escape(var) + r"=(\{[^}]{0,300}\})", js)
    print("[sonda] YF =", var, d.group(1) if d else None)
for m in re.finditer(r"search/products\",\{\.\.\.t,params:\{[^}]{0,200}", js):
    print("[sonda] params:", m.group(0)[:200])
for m in re.finditer(r".{0,300}ecommerce/search/products.{0,50}", js):
    print("[sonda] chamada:", m.group(0)[:360])

for caminho in ("v1/ecommerce/search/products?limit=36&offset=0&q=wd13fg",
                "v1/ecommerce/search/products?limit=36&offset=0&searchText=wd13fg",
                "v1/ecommerce/search/products?limit=36&offset=0&query=wd13fg",
                "v1/ecommerce/search/products?limit=36&offset=0&term=wd13fg",
                "v1/search/products?searchText=wd13fg",
                "v1/search/products?q=wd13fg",
                "v1/ecommerce/productsWithSkus/11956898/authorized",
                "v1/ecommerce/products/11956898/featured-items"):
    for extra in ({}, {"headers": {"x-inter-affiliate": "BANCOINTER"}}):
        st, txt = get(f"{API}/{caminho}", **extra)
        print(f"[sonda] {caminho} {'+hdr' if extra else ''} -> {st} {len(txt)} :: {txt[:260]!r}")
        if st == 200:
            break

st, txt = get("https://shopping.inter.co/x/r/11956898")
t = re.search(r"<title[^>]*>(.*?)</title>", txt, re.S)
print("[sonda] r/11956898 title:", t.group(1) if t else None, "len", len(txt))
nd = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', txt, re.S)
print("[sonda] r/ next_data:", nd.group(1)[:1200] if nd else None)
