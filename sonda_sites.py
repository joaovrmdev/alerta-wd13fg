"""Sonda temporária: quais lojas de perfume deixam o robô ler o Azzaro Wanted EDT 100ml (e se há cupons)."""
import json, os, re
os.environ["CONFIG"] = "config-azzaro-wanted.json"
import alerta as a

q = "azzaro%20wanted"
sites = {
    "Sephora (busca)": "https://www.sephora.com.br/search?q=azzaro+wanted",
    "Sephora (API)": "https://www.sephora.com.br/on/demandware.store/Sites-Sephora_BR-Site/pt_BR/Search-UpdateGrid?q=azzaro%20wanted&sz=24",
    "Beleza na Web": "https://www.belezanaweb.com.br/busca/?q=azzaro+wanted",
    "Drogasil": "https://www.drogasil.com.br/search?w=azzaro+wanted",
    "Droga Raia": "https://www.drogaraia.com.br/search?w=azzaro+wanted",
    "Pague Menos (VTEX)": f"https://www.paguemenos.com.br/api/catalog_system/pub/products/search?ft={q}",
    "The Beauty Box (VTEX)": f"https://www.thebeautybox.com.br/api/catalog_system/pub/products/search?ft={q}",
    "Netfarma (VTEX)": f"https://www.netfarma.com.br/api/catalog_system/pub/products/search?ft={q}",
    "Sumirê (VTEX)": f"https://www.perfumariasumire.com.br/api/catalog_system/pub/products/search?ft={q}",
    "Panvel": "https://www.panvel.com/panvel/buscarProduto.do?termoPesquisa=azzaro+wanted",
    "Drogaria Araujo (VTEX)": f"https://www.drogariaaraujo.com.br/api/catalog_system/pub/products/search?ft={q}",
    "Americanas": "https://www.americanas.com.br/busca/azzaro-wanted-eau-de-toilette-100ml",
    "Amazon (busca)": "https://www.amazon.com.br/s?k=perfume+azzaro+wanted+eau+de+toilette",
    "Magalu": "https://www.magazineluiza.com.br/busca/azzaro+wanted/",
    "Carrefour (VTEX)": f"https://www.carrefour.com.br/api/catalog_system/pub/products/search?ft={q}",
    "Casas Bahia": "https://www.casasbahia.com.br/azzaro-wanted/b",
    "Promobit cupons Sephora": "https://www.promobit.com.br/cupons/loja/sephora/",
}
for nome, url in sites.items():
    fonte = {"nome": nome, "url": url}
    try:
        ofertas = a.consulta_fonte(fonte)
        print(f"[ok]    {nome}: {len(ofertas)} oferta(s) do Wanted EDT 100ml " +
              ", ".join(f"{a.brl(o.preco)}{' ' + o.forma if o.forma else ''}" for o in sorted(ofertas, key=lambda o: o.preco)[:3]))
        for o in sorted(ofertas, key=lambda o: o.preco)[:2]:
            print(f"          {o.titulo[:90]} | {o.url[:80]}")
    except Exception as e:
        print(f"[falha] {nome}: {str(e)[:110]}")

print("\n#### cupons no Promobit (página da loja)")
for loja in ("sephora", "epoca-cosmeticos", "beleza-na-web", "drogasil", "mercado-livre", "amazon"):
    url = f"https://www.promobit.com.br/cupons/loja/{loja}/"
    try:
        t, _ = a.baixa(url)
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', t, re.S)
        d = json.loads(m.group(1)) if m else {}
        achados = []
        def anda(x, prof=0):
            if prof > 12: return
            if isinstance(x, dict):
                tit = x.get("couponTitle") or x.get("coupon_title") or x.get("title")
                cod = x.get("couponCode") or x.get("coupon_code") or x.get("code")
                if tit and (cod or "cupom" in str(tit).lower()):
                    achados.append((str(tit)[:80], cod, x.get("couponExpiration") or x.get("expiration") or x.get("couponEndDate")))
                for v in x.values(): anda(v, prof + 1)
            elif isinstance(x, list):
                for v in x[:60]: anda(v, prof + 1)
        anda(d)
        print(f"  {loja}: {len(achados)} cupom(ns)", achados[:3])
    except Exception as e:
        print(f"  {loja}: falhou {str(e)[:80]}")
