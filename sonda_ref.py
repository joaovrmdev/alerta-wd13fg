"""Sonda temporária: o que a busca do Buscapé devolve para títulos de ofertas (para preço de referência)."""
import json, re, html
from urllib.parse import quote
import cacador as c

titulos = ["Smartwatch Samsung Galaxy Fit3 Display 1.6\" Grafite", "Headset Gamer Machenike GX30, Som Surround 7.1",
           "Splitter HDMI 4 Portas MD9 - 7148", "Robô Aspirador Inteligente com Mapeamento Wi-Fi",
           "Air Fryer Mondial 4L AFN-40"]
for t in titulos:
    q = " ".join(re.sub(r"[^\w\s\-.]", " ", t).split()[:6])
    url = f"https://www.buscape.com.br/busca/{quote(q)}"
    print("\n#####", q, "|", url)
    try:
        texto = c.baixa(url)
    except Exception as e:  # noqa: BLE001
        print("  falhou", e); continue
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', texto, re.S)
    if not m:
        print("  sem __NEXT_DATA__; tamanho", len(texto)); continue
    d = json.loads(m.group(1))
    achados = []
    def anda(x, caminho=""):
        if isinstance(x, dict):
            if "name" in x and any(k in x for k in ("price", "minPrice", "lowestPrice")) and isinstance(x.get("name"), str):
                achados.append((caminho, x))
            for k, v in x.items():
                anda(v, caminho + "/" + k)
        elif isinstance(x, list):
            for i, v in enumerate(x[:60]):
                anda(v, caminho + f"[{i}]")
    anda(d)
    print("  itens com nome+preço:", len(achados), "| caminhos:", sorted({re.sub(r'\[\d+\]', '[]', p) for p, _ in achados})[:4])
    if achados:
        print("  CHAVES do 1º:", sorted(achados[0][1].keys()))
        print("  1º:", json.dumps(achados[0][1], ensure_ascii=False)[:1200])
    for _, x in achados[:5]:
        print("   -", x.get("name", "")[:70], "| price", x.get("price"), "| min", x.get("minPrice"), "| lowering", x.get("loweringPercentage"),
              "| ofertas", x.get("offersCount") or x.get("numberOfOffers") or len(x.get("merchants") or []), "| url", str(x.get("url") or x.get("productUrl"))[:60])
