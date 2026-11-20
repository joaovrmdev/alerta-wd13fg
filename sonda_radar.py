"""Sonda temporária: tamanho da categoria de perfumes, EAN e ListPrice."""
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote
import cacador as c

LOJAS = {"Época": ("www.epocacosmeticos.com.br", "/1000001/"), "Drogaria SP": ("www.drogariasaopaulo.com.br", "/1245/"),
         "Pacheco": ("www.drogariaspacheco.com.br", "/1245/"), "Extrafarma": ("www.extrafarma.com.br", "/300/879/"),
         "Pague Menos": ("www.paguemenos.com.br", "/300/879/")}

def total(host, cat):
    r = c.navegador.get(f"https://{host}/api/catalog_system/pub/products/search?fq=C:{quote(cat)}&_from=0&_to=0",
                        timeout=30, **c.IMITAR)
    return r.headers.get("resources"), r.status_code

def le_tudo(nome, host, cat, n):
    t0 = time.time(); skus = eans = lp = disp = 0; paginas = 0; erros = 0
    for ini in range(0, min(n, 2500), 50):
        url = f"https://{host}/api/catalog_system/pub/products/search?fq=C:{quote(cat)}&_from={ini}&_to={ini + 49}&O=OrderByNameASC"
        try:
            lista = c.baixa(url, json_=True)
        except Exception as e:
            erros += 1; print(nome, "erro", ini, e); continue
        paginas += 1
        for p in lista:
            for it in p.get("items", []):
                skus += 1
                eans += bool(it.get("ean"))
                of = ((it.get("sellers") or [{}])[0]).get("commertialOffer") or {}
                disp += bool(of.get("AvailableQuantity"))
                lp += (of.get("ListPrice") or 0) > (of.get("Price") or 0) + 1
    return f"{nome}: {paginas} páginas, {skus} SKUs ({disp} c/ estoque, {eans} c/ EAN, {lp} com 'de' maior), {erros} erros, {time.time()-t0:.0f}s"

tot = {}
for nome, (host, cat) in LOJAS.items():
    res, st = total(host, cat)
    print(nome, "resources:", res, st)
    tot[nome] = int(res.split("/")[-1]) if res and "/" in res else 500
t0 = time.time()
with ThreadPoolExecutor(5) as ex:
    for linha in ex.map(lambda kv: le_tudo(kv[0], *kv[1], tot[kv[0]]), LOJAS.items()):
        print(linha)
print(f"tudo em {time.time()-t0:.0f}s")
d = c.baixa("https://www.drogariasaopaulo.com.br/api/catalog_system/pub/products/search?ft=azzaro%20wanted", json_=True)
it = d[0]["items"][0]; of = it["sellers"][0]["commertialOffer"]
print("exemplo:", d[0].get("productName"), d[0].get("link"), it.get("ean"), it.get("itemId"), of.get("Price"), of.get("ListPrice"), of.get("PriceWithoutDiscount"))
