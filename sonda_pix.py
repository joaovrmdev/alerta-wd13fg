"""Sonda temporária: onde cada loja mostra o preço no PIX e o parcelado sem juros (só imprime)."""
import html
import json
import os
import re

os.environ.setdefault("CONFIG", "config.json")
import alerta  # noqa: E402

PALAVRAS = re.compile(r"(?i)(pix|sem juros|parcel|installment|à vista|a vista|avista|spotprice)")


def limpa(t: str) -> str:
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", t)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", t)).split())


def contextos(rotulo: str, t: str, n: int = 8, raio: int = 140) -> None:
    vistos = 0
    for m in PALAVRAS.finditer(t):
        i = m.start()
        print(f"   [{rotulo}] …{t[max(0, i - raio):i + raio]!r}")
        vistos += 1
        if vistos >= n:
            break
    if not vistos:
        print(f"   [{rotulo}] (nada)")


def samsung_api() -> None:
    url = "https://shop.samsung.com/br/api/catalog_system/pub/products/search?ft=wd13fg"
    texto, _ = alerta.baixa(url)
    for p in json.loads(texto):
        for it in p.get("items", []):
            for s in it.get("sellers", []):
                o = s.get("commertialOffer", {})
                print(f"\n== {it.get('name')} | seller {s.get('sellerName')}")
                print("   Price", o.get("Price"), "ListPrice", o.get("ListPrice"),
                      "PriceWithoutDiscount", o.get("PriceWithoutDiscount"), "spotPrice", o.get("spotPrice"),
                      "Qtd", o.get("AvailableQuantity"))
                por_sistema = {}
                for x in o.get("Installments", []):
                    por_sistema.setdefault(x.get("PaymentSystemName"), []).append(
                        (x.get("NumberOfInstallments"), x.get("Value"), x.get("InterestRate"),
                         x.get("TotalValuePlusInterestRate")))
                for nome, lst in por_sistema.items():
                    lst.sort()
                    print(f"   inst {nome}: primeiro {lst[0]} | último {lst[-1]}")
                for chave in ("Teasers", "PromotionTeasers", "DiscountHighLight"):
                    if o.get(chave):
                        print(f"   {chave}: {json.dumps(o[chave], ensure_ascii=False)[:600]}")
        extras = {k: v for k, v in p.items() if re.search(r"(?i)pix|desconto|promo", k)}
        if extras:
            print("   campos do produto:", json.dumps(extras, ensure_ascii=False)[:600])


def pagina(rotulo: str, url: str) -> None:
    print(f"\n######## {rotulo} — {url}")
    try:
        texto, final = alerta.baixa(url)
    except Exception as e:  # noqa: BLE001
        print("   falhou:", e)
        return
    print("   final:", final, "| tamanho", len(texto))
    contextos("texto", limpa(texto))
    cru = html.unescape(texto)
    for chave in re.findall(r'"([A-Za-z_]*(?:[Ii]nstallment|[Pp]ix|[Ss]pot)[A-Za-z_]*)"\s*:', cru)[:30]:
        print("   chave json:", chave)
    for m in list(re.finditer(r'"[A-Za-z_]*(?:[Ii]nstallment|[Pp]ix)[A-Za-z_]*"\s*:', cru))[:6]:
        print(f"   [json] {cru[m.start():m.start() + 260]!r}")


if __name__ == "__main__":
    print("######## Samsung API")
    try:
        samsung_api()
    except Exception as e:  # noqa: BLE001
        print("   falhou:", e)
    pagina("Samsung página", "https://shop.samsung.com/br/lava-seca-smart-samsung-ai-control-wd13fg-inox-13kg/p")
    pagina("Amazon produto", "https://www.amazon.com.br/dp/B0FWMTLMR4")
    pagina("Buscapé inox", "https://www.buscape.com.br/lavadora-roupas/lava-e-seca-samsung-13kg-eco-bubble-smart-ai-control-wd13fg-wd13fg6b34bx-cor-inox")
    pagina("Zoom busca", "https://www.zoom.com.br/busca/wd13fg")
    pagina("Amazon multiprocessador", "https://www.amazon.com.br/s?k=mondial+mpn-01-bf")
