"""Sonda temporária: id da categoria de perfumes em cada loja VTEX e leitura por categoria."""
import time
from urllib.parse import quote
import cacador as c

LOJAS = {"Época": "www.epocacosmeticos.com.br", "Drogaria SP": "www.drogariasaopaulo.com.br",
         "Pacheco": "www.drogariaspacheco.com.br", "Extrafarma": "www.extrafarma.com.br", "Pague Menos": "www.paguemenos.com.br"}
for nome, host in LOJAS.items():
    d = c.baixa(f"https://{host}/api/catalog_system/pub/products/search?ft={quote('azzaro wanted')}", json_=True)
    cats = {}
    for p in d[:6]:
        for nomecat, ids in zip(p.get("categories", []), p.get("categoriesIds", [])):
            cats[ids] = nomecat
    print(f"\n{nome}: categorias dos produtos Azzaro:", sorted(cats.items(), key=lambda x: len(x[0]))[:6])
    # a categoria mais rasa que contém "perf" / "fragr"
    alvo = sorted((i for i, n in cats.items() if any(x in n.lower() for x in ("perf", "fragr"))), key=len)
    if not alvo:
        continue
    fq = alvo[0]
    t0 = time.time(); total = disp = 0; nomes = []
    for pagina in range(6):
        ini = pagina * 50
        url = f"https://{host}/api/catalog_system/pub/products/search?fq=C:{quote(fq)}&_from={ini}&_to={ini + 49}&O=OrderByTopSaleDESC"
        try:
            lista = c.baixa(url, json_=True)
        except Exception as e:
            print("  erro", e); break
        if not lista:
            break
        for p in lista:
            for it in p.get("items", []):
                total += 1
                if (((it.get("sellers") or [{}])[0]).get("commertialOffer") or {}).get("AvailableQuantity"):
                    disp += 1
            if len(nomes) < 5:
                nomes.append(p.get("productName", "")[:55])
    print(f"  fq=C:{fq} ({cats[fq]}): {total} SKUs ({disp} com estoque) em {time.time()-t0:.0f}s | top: {nomes}")
