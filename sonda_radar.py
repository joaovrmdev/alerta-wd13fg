"""Sonda temporária: o que a busca do Zoom/Buscapé mostra para 'dreame h60 gt' e de onde o plano B tirou o preço."""
import os, re, html, json
os.environ["CONFIG"] = "config-dreame-h60gt.json"
import alerta as a

for url in ["https://www.zoom.com.br/busca/dreame%20h60%20gt", "https://www.buscape.com.br/busca/dreame%20h60%20gt"]:
    texto, final = a.baixa(url)
    print(f"\n===== {url} -> {final} ({len(texto)} bytes)")
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', texto, re.S)
    if m:
        d = json.loads(m.group(1))
        hits = (((d.get("props") or {}).get("initialReduxState") or {}).get("hits") or {}).get("hits") or []
        print(f"hits: {len(hits)}")
        for h in hits[:15]:
            s = h.get("_source") or h
            print("   ", (s.get("name") or s.get("title") or "")[:90], "|", s.get("price") or s.get("minPrice") or s.get("bestPrice"))
        # outras chaves úteis
        st = (d.get("props") or {}).get("initialReduxState") or {}
        print("chaves do estado:", list(st.keys())[:20])
    t = html.unescape(texto).replace('\\"', '"').replace("\\u002F", "/")
    t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t))
    for mm in list(re.finditer(r"H60 GT", t, re.I))[:8]:
        print("  >>> trecho:", t[max(0, mm.start() - 120): mm.end() + 260].replace("\n", " "))
    print("plano B:", [(o.titulo, o.preco) for o in a.varre_texto(texto, {"nome": "Zoom", "url": url})])
