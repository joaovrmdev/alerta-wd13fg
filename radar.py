#!/usr/bin/env python3
"""
Radar de preços: lê direto o catálogo das lojas (por enquanto, perfumes em cinco lojas VTEX), guarda o
histórico de preço de cada item (um mini-Keepa) e procura quedas fortes antes de virarem post em site de
promoção. O candidato passa pela mesma IA do caçador (com a contraprova de bug) e, se a nota for boa,
vai para o grupo.

Três sinais, todos configuráveis no radar.json:
  - queda no histórico da própria loja (e mais barato que as outras lojas, quando elas têm o item);
  - muito abaixo do mesmo código de barras (EAN) nas outras lojas;
  - muito abaixo do preço "de" que a própria loja mostra.

Uso:
    python radar.py              # rodada normal (respeita o intervalo do radar.json)
    python radar.py teste        # lê agora e manda só para você a análise do maior candidato
    python radar.py simulacao    # lê e mostra no log os candidatos (sem IA, sem mensagem, sem salvar)
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import cacador as c

BASE = Path(__file__).resolve().parent
CFG = json.loads((BASE / "radar.json").read_text(encoding="utf-8"))
ARQ_ESTADO = BASE / "estado-radar" / "radar.json"


@dataclass
class Item:
    chave: str          # loja:sku
    loja: str
    grupo: str          # lojas da mesma empresa não servem de comparação entre si
    nome: str
    url: str
    ean: str
    preco: float
    de: float | None = None
    vendedor: str = ""  # só quando não é a própria loja (marketplace)


@dataclass
class Candidato:
    item: Item
    motivos: list[str]
    forca: int                                  # maior queda em %, para ordenar
    referencia: float | None                    # preço normal estimado (histórico ou outras lojas)
    historico: list = field(default_factory=list)
    outras: list = field(default_factory=list)  # [(loja, preço)] do mesmo EAN em outras empresas
    mesma_queda: list = field(default_factory=list)  # outras lojas com o mesmo item também caído


# ------------------------------------------------------------------------- leitura
def le_categoria(loja: dict, categoria: str, paginas: int) -> tuple[list[dict], list[str]]:
    produtos, erros = [], []
    for pagina in range(min(paginas, 50)):  # a API da VTEX não passa de 2.500 resultados
        ini = pagina * 50
        url = (f"https://{loja['host']}/api/catalog_system/pub/products/search?fq=C:{quote(categoria)}"
               f"&_from={ini}&_to={ini + 49}&O=OrderByTopSaleDESC")
        try:
            lista = c.baixa(url, json_=True)
        except Exception as e:  # noqa: BLE001
            erros.append(f"página {pagina + 1}: {str(e)[:80]}")
            if len(erros) >= 3:
                break
            continue
        if not isinstance(lista, list) or not lista:
            break
        produtos += lista
        if len(lista) < 50:
            break
    return produtos, erros


def itens_da_loja(loja: dict, produtos: list[dict]) -> list[Item]:
    achados: dict[str, Item] = {}
    for p in produtos:
        base = (p.get("productName") or "").strip()
        link = p.get("link") or f"https://{loja['host']}/"
        skus = p.get("items") or []
        for it in skus:
            ofertas = []
            for s in it.get("sellers") or []:
                of = s.get("commertialOffer") or {}
                if of.get("AvailableQuantity") and (of.get("Price") or 0) > 0:
                    ofertas.append((float(of["Price"]), float(of.get("ListPrice") or 0), s))
            if not ofertas:
                continue
            preco, de, vendedor = min(ofertas, key=lambda x: x[0])
            if max(preco, de) < CFG.get("preco_minimo", 0):
                continue
            nome = base
            nome_sku = (it.get("name") or "").strip()
            if len(skus) > 1 and nome_sku and c.normaliza(nome_sku) not in c.normaliza(base):
                nome = f"{base} {nome_sku}"
            sku = str(it.get("itemId"))
            terceiro = str(vendedor.get("sellerId") or "1") != "1"
            achados[f"{loja['id']}:{sku}"] = Item(
                chave=f"{loja['id']}:{sku}", loja=loja["nome"], grupo=loja.get("grupo") or loja["id"], nome=nome,
                url=f"{link}?skuId={sku}" if len(skus) > 1 else link, ean=str(it.get("ean") or "").strip(),
                preco=round(preco, 2), de=round(de, 2) if de > preco + 0.5 else None,
                vendedor=(vendedor.get("sellerName") or "") if terceiro else "")
    return list(achados.values())


def le_loja(loja: dict) -> tuple[dict, list[Item], str | None, str]:
    """Roda em paralelo (uma loja por vez em cada linha); o log volta como texto para não embaralhar."""
    t0 = time.monotonic()
    produtos, erros = [], []
    for cat in loja.get("categorias") or []:
        p, e = le_categoria(loja, cat, CFG.get("paginas_por_categoria", 50))
        produtos += p
        erros += e
    itens = itens_da_loja(loja, produtos)
    log = (f"[radar] {loja['nome']}: {len(produtos)} produtos, {len(itens)} itens com estoque"
           f"{f', {len(erros)} página(s) com erro ({erros[0]})' if erros else ''} ({time.monotonic() - t0:.0f}s)")
    if not itens:
        return loja, [], f"nenhum item lido ({erros[0] if erros else 'catálogo vazio'})", log
    return loja, itens, None, log


# ------------------------------------------------------------------------ histórico
def referencia(entradas: list, hoje: int) -> tuple[float | None, float | None]:
    """Mediana e mínimo dos preços diários anteriores a esta leitura (inclui o de hoje até agora)."""
    inicio = hoje - CFG.get("dias_referencia", 14)
    valores = [p for d, p in entradas if d >= inicio]
    if not valores:
        return None, None
    return statistics.median(valores), min(valores)


def registra(historico: dict, itens: list[Item], hoje: int) -> None:
    for it in itens:
        ent = historico.setdefault(it.chave, [])
        if ent and ent[-1][0] == hoje:
            ent[-1][1] = min(ent[-1][1], it.preco)
        else:
            ent.append([hoje, it.preco])
        corte = hoje - CFG.get("dias_historico", 30)
        while ent and ent[0][0] < corte:
            ent.pop(0)
    corte = hoje - CFG.get("dias_historico", 30)
    for k in [k for k, v in historico.items() if not v or v[-1][0] < corte]:
        del historico[k]


def pct(preco: float, ref: float) -> int:
    return round(100 * (1 - preco / ref)) if ref else 0


def avalia(it: Item, historico: dict, por_ean: dict, hoje: int) -> Candidato | None:
    entradas = historico.get(it.chave) or []
    ref, minimo = referencia(entradas, hoje)
    outras = [(loja, p) for loja, grupo, p in por_ean.get(it.ean, []) if grupo != it.grupo] if it.ean else []
    grupos = {g for _, g, _ in por_ean.get(it.ean, []) if g != it.grupo} if it.ean else set()
    med_outras = statistics.median(p for _, p in outras) if outras else None
    min_outras = min(p for _, p in outras) if outras else None
    queda_propria = ref is None or it.preco <= ref * 0.85        # caiu em relação à própria loja (ou sem histórico)
    abaixo_de_todas = min_outras is None or it.preco <= min_outras * 0.9

    motivos, forca = [], 0
    q = CFG.get("queda_minima_pct", 40)
    if ref and it.preco <= ref * (1 - q / 100) and it.preco < minimo * 0.97 and abaixo_de_todas:
        motivos.append(f"queda de {pct(it.preco, ref)}% no histórico da loja (normal {c.brl(ref)})")
        forca = max(forca, pct(it.preco, ref))
    q = CFG.get("abaixo_outras_lojas_pct", 40)
    if (len(grupos) >= 2 and it.preco <= med_outras * (1 - q / 100) and it.preco <= min_outras * 0.8
            and queda_propria):
        motivos.append(f"{pct(it.preco, med_outras)}% abaixo das outras lojas (mediana {c.brl(med_outras)})")
        forca = max(forca, pct(it.preco, med_outras))
    q = CFG.get("desconto_declarado_pct", 80)
    if (it.de and it.de >= CFG.get("preco_de_minimo", 150) and it.preco <= it.de * (1 - q / 100)
            and queda_propria and (min_outras is None or it.preco <= min_outras * 0.8)):
        motivos.append(f"{pct(it.preco, it.de)}% abaixo do preço \"de\" da loja ({c.brl(it.de)})")
        forca = max(forca, pct(it.preco, it.de))
    if not motivos:
        return None
    return Candidato(it, motivos, forca, ref or med_outras or it.de, list(entradas), outras)


def maior_queda(it: Item, historico: dict, por_ean: dict, hoje: int) -> Candidato:
    """Para o modo teste: o tamanho da queda mesmo sem passar das réguas."""
    ref, _ = referencia(historico.get(it.chave) or [], hoje)
    outras = [(loja, p) for loja, grupo, p in por_ean.get(it.ean, []) if grupo != it.grupo] if it.ean else []
    med = statistics.median(p for _, p in outras) if outras else None
    opcoes = [(pct(it.preco, r), r, nome) for r, nome in ((ref, "histórico da loja"), (med, "outras lojas"))
              if r and r > it.preco]
    forca, r, nome = max(opcoes, default=(0, None, ""))
    return Candidato(it, [f"teste: {forca}% abaixo ({nome})" if r else "teste"], forca, r,
                     list(historico.get(it.chave) or []), outras)


def candidatos(itens: list[Item], historico: dict, hoje: int) -> tuple[list[Candidato], dict]:
    por_ean: dict[str, list] = {}
    for it in itens:
        if it.ean:
            por_ean.setdefault(it.ean, []).append((it.loja, it.grupo, it.preco))
    achados = [cand for it in itens if (cand := avalia(it, historico, por_ean, hoje))]
    # o mesmo produto caído em mais de uma loja vira um candidato só (o mais barato), citando as outras
    unicos: dict[str, Candidato] = {}
    for cand in sorted(achados, key=lambda x: x.item.preco):
        k = f"ean:{cand.item.ean}" if cand.item.ean else cand.item.chave
        if k in unicos:
            unicos[k].mesma_queda.append((cand.item.loja, cand.item.preco))
        else:
            unicos[k] = cand
    return sorted(unicos.values(), key=lambda x: -x.forca), por_ean


def chave_aviso(cand: Candidato) -> str:
    return f"ean:{cand.item.ean}" if cand.item.ean else cand.item.chave


def ja_analisado(estado: dict, cand: Candidato, agora: datetime) -> bool:
    """Não gasta IA de novo com o mesmo item, a menos que o preço tenha caído mais 10%."""
    antes = (estado.get("analisados") or {}).get(chave_aviso(cand))
    if not antes:
        return False
    recente = agora - datetime.fromisoformat(antes["t"]) < timedelta(days=CFG.get("nao_repetir_dias", 3))
    return recente and cand.item.preco > antes["p"] * 0.9


# --------------------------------------------------------------------------- oferta
def data_curta(dia: int) -> str:
    return date.fromordinal(dia).strftime("%d/%m")


def oferta(cand: Candidato, agora: datetime) -> c.Oferta:
    it = cand.item
    linhas = ["Achado pelo radar de preços: leitura direta do site da loja, não é post de site de promoção."]
    if cand.historico:
        hist = " · ".join(f"{data_curta(d)} {c.brl(p)}" for d, p in cand.historico[-10:])
        linhas.append(f"Histórico deste item nesta loja (menor preço com estoque por dia): {hist} · agora {c.brl(it.preco)}")
    else:
        linhas.append("Ainda não há histórico deste item nesta loja (primeira leitura).")
    if cand.outras:
        outras = " · ".join(f"{loja} {c.brl(p)}" for loja, p in sorted(cand.outras, key=lambda x: x[1]))
        linhas.append(f"Mesmo código de barras (EAN {it.ean}) agora em outras lojas: {outras}")
    if cand.mesma_queda:
        linhas.append("O mesmo item também caiu em: "
                      + " · ".join(f"{loja} {c.brl(p)}" for loja, p in cand.mesma_queda))
    if it.de:
        linhas.append(f"Preço \"de\" exibido pela loja: {c.brl(it.de)}")
    o = c.Oferta(fonte="Radar", id=it.chave, titulo=it.nome, url=it.url, preco=it.preco,
                 preco_antigo=round(cand.referencia, 2) if cand.referencia and cand.referencia > it.preco else None,
                 desconto=cand.forca or None, loja=it.loja, publicado=agora, texto="\n".join(linhas),
                 motivos=list(cand.motivos))
    o.vendido_por = it.vendedor
    return o


# --------------------------------------------------------------------------- estado
def carrega_estado() -> dict:
    try:
        return json.loads(ARQ_ESTADO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def salva_estado(estado: dict, agora: datetime) -> None:
    limite = (agora - timedelta(days=CFG.get("nao_repetir_dias", 3) + 1)).isoformat()
    estado["analisados"] = {k: v for k, v in (estado.get("analisados") or {}).items() if v["t"] >= limite}
    ARQ_ESTADO.parent.mkdir(parents=True, exist_ok=True)
    ARQ_ESTADO.write_text(json.dumps(estado, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    saida = os.getenv("GITHUB_OUTPUT")
    if saida:  # avisa o workflow que há histórico novo para guardar no cache
        with open(saida, "a", encoding="utf-8") as f:
            f.write("rodou=1\n")


def avisa_falhas(estado: dict, falhas: dict[str, str], lojas: list[dict], agora: datetime) -> None:
    contagem = estado.setdefault("falhas", {})
    for loja in lojas:
        nome = loja["nome"]
        contagem[nome] = contagem.get(nome, 0) + 1 if nome in falhas else 0
        if contagem[nome] == 3 and (estado.setdefault("aviso_falha", {}).get(nome) != agora.date().isoformat()):
            c.envia(f"<b>⚠️ Radar: não consigo ler a {c.esc(nome)}</b>\n"
                    + c.esc(f"3 leituras seguidas falharam: {falhas[nome]}"), so_para_mim=True)
            estado["aviso_falha"][nome] = agora.date().isoformat()


# ----------------------------------------------------------------------------- main
def main() -> int:
    modo = (sys.argv[1] if len(sys.argv) > 1 else "verificar").lower()
    if modo == "grupo":
        return 0
    simular = modo == "simulacao"
    teste = modo == "teste"
    c.SIMULAR = simular
    agora = datetime.now(c.BRT)
    hoje = agora.date().toordinal()
    estado = carrega_estado()
    ultima = estado.get("ultima_leitura")
    intervalo = timedelta(minutes=CFG.get("intervalo_minutos", 30) - 2)
    if modo == "verificar" and ultima and agora - datetime.fromisoformat(ultima) < intervalo:
        print(f"[radar] última leitura às {datetime.fromisoformat(ultima):%H:%M}; a próxima fica para depois")
        return 0

    lojas = [l for l in CFG["lojas"] if l.get("ativa", True)]
    itens: list[Item] = []
    falhas: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=len(lojas) or 1) as ex:
        for loja, achados, erro, log in ex.map(le_loja, lojas):
            print(log)
            itens += achados
            if erro:
                falhas[loja["nome"]] = erro
    if not itens:
        print("[radar] nenhuma loja respondeu")
        if not simular:
            avisa_falhas(estado, falhas, lojas, agora)
            salva_estado(estado, agora)
        return 0

    historico = estado.setdefault("historico", {})
    aquecendo = not estado.get("iniciado")
    achados, por_ean = candidatos(itens, historico, hoje)
    print(f"\n[radar] {len(itens)} itens lidos, {len(historico)} com histórico, {len(achados)} candidato(s)")
    for cand in achados[:15]:
        print(f"  - {cand.item.loja}: {c.brl(cand.item.preco)} | {'; '.join(cand.motivos)} | {cand.item.nome[:70]}")

    if teste and not achados:  # sem candidato: testa com a maior queda do momento
        achados = sorted((maior_queda(it, historico, por_ean, hoje) for it in itens), key=lambda x: -x.forca)[:1]

    analisados = estado.setdefault("analisados", {})
    if aquecendo and not teste:
        # primeira leitura: só monta o histórico. O que já estiver "caído" agora é marcado como visto, para
        # não chegar uma enxurrada de avisos velhos (ou de diferenças de cadastro entre lojas) de uma vez.
        for cand in achados:
            analisados[chave_aviso(cand)] = {"p": cand.item.preco, "t": agora.isoformat()}
        if not simular:
            estado["iniciado"] = agora.isoformat()
            c.envia("<b>📡 Radar de preços ligado</b>\n" + c.esc(
                f"{len(itens)} perfumes com estoque em {len(lojas) - len(falhas)} lojas. Agora vou montando o "
                "histórico de cada um e aviso quando algum cair forte."), so_para_mim=True)
        achados = []

    estado.pop("modelo_gemini", None)  # sempre começa pelo modelo preferido da lista do cacador.json
    teto_dia = CFG.get("max_analises_por_dia", 15)
    feitas, inicio, sem_ia = 0, time.monotonic(), None
    for cand in achados:
        if simular:
            break
        if feitas >= (1 if teste else CFG.get("max_analises_por_rodada", 2)) or time.monotonic() - inicio > 240:
            break
        if not teste and ja_analisado(estado, cand, agora):
            continue
        dia = c.conta_uso(estado, agora, None)
        if not teste and dia["analises"] >= teto_dia:
            print(f"  [teto] {dia['analises']} análises do radar hoje (limite {teto_dia})")
            break
        o = oferta(cand, agora)
        print(f"\n  [radar → IA] {o.loja}: {c.brl(o.preco)} | {o.titulo[:70]}")
        try:
            a = c.analisa(o, estado, agora, teste)
        except c.SemIA as e:
            sem_ia = str(e)
            print(f"  [sem IA] {sem_ia}")
            break
        feitas += 1
        analisados[chave_aviso(cand)] = {"p": cand.item.preco, "t": agora.isoformat()}
        bom = a["nota"] >= c.nota_de_aviso(a["veredito"]) and a["veredito"] in c.VEREDITOS_BONS
        if teste:
            c.envia(c.mensagem(o, a, teste=True), so_para_mim=True)
        elif bom:
            c.envia(c.mensagem(o, a))

    if teste and sem_ia:
        c.envia(c.esc(f"⚠️ Radar: {sem_ia}"), so_para_mim=True)

    registra(historico, itens, hoje)
    if simular:
        print("[simulação] histórico não salvo")
        return 0
    avisa_falhas(estado, falhas, lojas, agora)
    estado["ultima_leitura"] = agora.isoformat()
    salva_estado(estado, agora)
    dia = estado.get("ia_dia") or {}
    print(f"[radar] IA hoje: {dia.get('analises', 0)} análise(s); histórico de {len(historico)} itens salvo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
