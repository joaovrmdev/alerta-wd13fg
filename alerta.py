#!/usr/bin/env python3
"""
Alerta de promoção (começou com a Samsung WD13FG, lava e seca).

Roda no GitHub Actions: lê o preço em várias lojas e manda mensagem no
Telegram (e, se configurado, Discord e WhatsApp) quando o preço chega no alvo
ou cai de repente. Uma vez por dia manda um resumo, que também serve para saber
que o alerta está vivo.

Cada produto tem o seu arquivo de configuração. O padrão é config.json; para
outro produto, aponte a variável CONFIG para o arquivo dele (cada um guarda o
seu próprio histórico em estado/).

Uso:
    python alerta.py             # verificação normal (o que o agendamento roda)
    python alerta.py teste       # manda um resumo agora, para testar as mensagens
    python alerta.py simulacao   # só mostra no log o que mandaria (usado nos pull requests)
    CONFIG=config-glamy.json python alerta.py teste   # o mesmo, para outro produto
"""
from __future__ import annotations

import html
import json
import os
import random
import re
import statistics
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote_plus, urljoin

import requests

try:  # curl_cffi imita o "jeito" do Chrome, o que reduz bloqueio das lojas
    from curl_cffi import requests as navegador

    IMITAR = {"impersonate": "chrome"}
except ImportError:  # pragma: no cover
    navegador = requests
    IMITAR = {}

BASE = Path(__file__).resolve().parent
ARQ_CONFIG = BASE / os.getenv("CONFIG", "config.json")
CFG = json.loads(ARQ_CONFIG.read_text(encoding="utf-8"))
# config.json mantém o nome antigo do estado, para não perder o histórico que já existe
ARQ_ESTADO = BASE / "estado" / ("estado.json" if ARQ_CONFIG.name == "config.json"
                                else f"estado-{ARQ_CONFIG.stem}.json")
BRT = timezone(timedelta(hours=-3))
MIN_VALIDO, MAX_VALIDO = CFG.get("faixa_de_preco_valida", [2500, 15000])
URLS_FONTES = {f["url"] for f in CFG["fontes"]}

CABECALHOS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.6,en;q=0.5",
}
CHAVES_NOME = ("name", "title", "productName", "nameComplete", "productTitle", "nome", "titulo")
CHAVES_LOJA = ("storeName", "sellerName", "merchantName", "store", "seller", "merchant",
               "loja", "vendedor", "retailer", "shopName", "shop")
CHAVES_URL = ("url", "link", "href", "productUrl", "permalink", "offerUrl", "canonical")
CHAVE_PRECO = re.compile(
    r"(?i)^(price|lowprice|bestprice|saleprice|spotprice|pixprice|cashprice|finalprice|"
    r"offerprice|currentprice|pricevalue|pricewithdiscount|sellingprice|minprice|"
    r"bestpricevalue|preco|precopix|precoavista|precopromocional)$"
)
CHAVE_PARCELA = re.compile(r"(?i)installment|parcel")
SINAIS_DE_BLOQUEIO = ("captcha", "access denied", "just a moment", "are you a robot",
                      "verifique que você é humano", "request blocked", "attention required")


@dataclass
class Oferta:
    titulo: str
    preco: float
    loja: str
    url: str
    fonte: str
    estimado: bool = False
    forma: str = ""                 # "no PIX" / "à vista" quando a loja diz como é esse preço
    parcelas: int | None = None     # melhor parcelamento que a loja mostra
    parcela: float | None = None
    sem_juros: bool | None = None
    total: float | None = None      # total parcelado informado pela loja (se houver)

    @property
    def total_parcelado(self) -> float | None:
        if self.total:
            return self.total
        return round(self.parcelas * self.parcela, 2) if self.parcelas and self.parcela else None

    @property
    def parcelado_menor(self) -> bool:
        """Raro, mas acontece: o total parcelado sair abaixo do preço à vista/PIX."""
        total = self.total_parcelado
        return bool(self.parcelas and self.parcelas >= 2 and total and total < self.preco - 0.5)

    @property
    def custo(self) -> float:
        """O menor valor para levar o produto: PIX/à vista ou o total parcelado."""
        return self.total_parcelado if self.parcelado_menor else self.preco  # type: ignore[return-value]


# ----------------------------------------------------------------- texto e preço
def normaliza(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


MODELOS = [re.sub(r"[\s\-_/]", "", normaliza(k)) for k in CFG["palavras_chave"]]
# termos que também precisam aparecer (ex.: "com tampo", para não pegar a versão sem tampo)
EXIGIDOS = [re.sub(r"[\s\-_/]", "", normaliza(k)) for k in CFG.get("exigir_tambem") or []]


def bate_modelo(titulo: str) -> bool:
    t = re.sub(r"[\s\-_/]", "", normaliza(titulo))
    return any(m in t for m in MODELOS) and all(e in t for e in EXIGIDOS)


def excluido(titulo: str) -> bool:
    t = normaliza(titulo)
    if any(normaliza(p) in t for p in CFG.get("excluir_se_tiver", [])):
        return True
    volt = (CFG.get("voltagem") or "").upper()
    # código Samsung: ...AZ = 127V, ...BZ = 220V (ex.: WD13FG6B34BXAZ / WD13FG6B34BXBZ)
    tem_127 = re.search(r"(?<!\d)(110|127)\s*v|b34b[xbe]/?az", t)
    tem_220 = re.search(r"(?<!\d)220\s*v|b34b[xbe]/?bz", t)
    if volt.startswith(("110", "127")) and tem_220 and not tem_127:
        return True
    if volt.startswith("220") and tem_127 and not tem_220:
        return True
    return False


CORES = [normaliza(c) for c in CFG.get("cores_aceitas") or []]


def cor_ok(titulo: str) -> bool:
    """Só aceita anúncios que dizem uma das cores escolhidas (se a lista não estiver vazia)."""
    t = normaliza(titulo)
    return not CORES or any(c in t for c in CORES)


def para_numero(v) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if not isinstance(v, str):
        return None
    s = v.replace("R$", "").replace("\xa0", "").replace(" ", "").strip()
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d{1,2})?|\d+,\d{1,2}", s):  # 4.049,10 / 4049,10
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d{1,2})?", s):  # 4,049.10
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def no_intervalo(bruto) -> float | None:
    """Converte e só aceita valores plausíveis (corta parcelas, acessórios, IDs)."""
    p = para_numero(bruto)
    if p is None:
        return None
    if MIN_VALIDO <= p <= MAX_VALIDO:
        return round(p, 2)
    if isinstance(bruto, int) and MIN_VALIDO <= p / 100 <= MAX_VALIDO:  # preço em centavos
        return round(p / 100, 2)
    return None


def brl(v: float) -> str:
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ------------------------------------------------------- leitura de dados da página
def nome_de(d: dict) -> str | None:
    for k in CHAVES_NOME:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def indisponivel(d: dict) -> bool:
    disp = str(d.get("availability", "")).lower()
    if any(x in disp for x in ("outofstock", "soldout", "discontinued")):
        return True
    if d.get("AvailableQuantity") == 0:
        return True
    return any(d.get(k) is False for k in ("available", "isAvailable", "disponivel"))


def ignorar_filho(d: dict) -> bool:
    """Não misturar preço de outro produto (relacionados, outra voltagem...)."""
    if indisponivel(d):
        return True
    n = nome_de(d)
    if not n:
        return False
    if bate_modelo(n):
        return excluido(n)
    return len(n) >= 25  # nome longo sem o modelo = outro produto


def precos_de(obj, prof: int = 0, sob_chave_preco: bool = False) -> list[float]:
    achados: list[float] = []
    if prof > 6:
        return achados
    if isinstance(obj, dict):
        for k, v in obj.items():
            if CHAVE_PARCELA.search(str(k)):  # valor de parcela não é preço do produto
                continue
            k_preco = bool(CHAVE_PRECO.match(str(k))) or (
                sob_chave_preco and str(k).lower() in ("value", "amount"))
            if isinstance(v, dict):
                if not ignorar_filho(v):
                    achados += precos_de(v, prof + 1, k_preco)
            elif isinstance(v, list):
                achados += precos_de(v, prof + 1, k_preco)
            elif k_preco:
                p = no_intervalo(v)
                if p is not None:
                    achados.append(p)
    elif isinstance(obj, list):
        for item in obj[:300]:
            if isinstance(item, dict) and ignorar_filho(item):
                continue
            if isinstance(item, (dict, list)):
                achados += precos_de(item, prof + 1, sob_chave_preco)
            elif sob_chave_preco:
                p = no_intervalo(item)
                if p is not None:
                    achados.append(p)
    return achados


def loja_de(d: dict) -> str | None:
    for k in CHAVES_LOJA:
        v = d.get(k)
        if isinstance(v, str) and 1 < len(v) < 60:
            return v.strip()
        if isinstance(v, dict):
            n = nome_de(v) or v.get("name")
            if isinstance(n, str) and n.strip():
                return n.strip()
    offers = d.get("offers")
    if isinstance(offers, dict):
        return loja_de(offers)
    return None


def url_de(d: dict, base: str) -> str:
    for k in CHAVES_URL:
        v = d.get(k)
        if isinstance(v, str) and v.startswith("http"):
            return v
        if isinstance(v, str) and v.startswith("/") and not v.startswith("//"):
            return urljoin(base, v)
    return base


def _num(d: dict, *chaves):
    for k in chaves:
        v = para_numero(d.get(k))
        if v:
            return v
    return None


def condicoes(obj, prof: int = 0) -> list[dict]:
    """Formas de pagamento junto de cada preço: valor no PIX e parcelamento.

    Entende o formato VTEX (lista "Installments" por meio de pagamento, ex.: Samsung, Fast Shop) e o
    formato {"installments": {"amount_months", "price", "total_value"}} (ex.: Buscapé/Zoom).
    """
    achadas: list[dict] = []
    if prof > 8:
        return achadas
    if isinstance(obj, list):
        for item in obj[:300]:
            if isinstance(item, (dict, list)) and not (isinstance(item, dict) and ignorar_filho(item)):
                achadas += condicoes(item, prof + 1)
        return achadas
    if not isinstance(obj, dict):
        return achadas
    base = [p for k, v in obj.items() if CHAVE_PRECO.match(str(k)) and not isinstance(v, (dict, list))
            for p in [no_intervalo(v)] if p is not None]
    inst = next((v for k, v in obj.items() if str(k).lower() in ("installments", "installment")), None)
    if base and isinstance(inst, list):  # VTEX
        pix, melhor = None, None
        for x in inst:
            if not isinstance(x, dict):
                continue
            n, valor = int(_num(x, "NumberOfInstallments") or 0), _num(x, "Value")
            if not (n and valor):
                continue
            if n == 1 and "pix" in str(x.get("PaymentSystemName", "")).lower():
                pix = min(pix or valor, valor)
            elif n >= 2 and not x.get("InterestRate") and (melhor is None or n > melhor[0]
                                                           or (n == melhor[0] and valor < melhor[1])):
                melhor = (n, valor, _num(x, "TotalValuePlusInterestRate"))
        achadas.append({"base": min(base), "pix": no_intervalo(pix) if pix else None,
                        "parcelas": melhor[0] if melhor else None, "parcela": melhor[1] if melhor else None,
                        "sem_juros": True if melhor else None, "total": melhor[2] if melhor else None})
    elif base and isinstance(inst, dict):  # Buscapé / Zoom
        n, valor = _num(inst, "amount_months", "months", "count", "quantity"), _num(inst, "price", "value")
        total = _num(inst, "total_value", "total")
        if n and n >= 2 and valor and valor >= min(base) * 0.9:  # algumas lojas mandam o total no lugar da parcela
            valor, total = round(valor / n, 2), valor
        if n and n >= 2 and valor:
            juros = inst.get("interest", inst.get("interestRate"))
            achadas.append({"base": min(base), "pix": None, "parcelas": int(n), "parcela": valor,
                            "sem_juros": (juros == 0) if juros is not None else None, "total": total})
    for v in obj.values():
        if isinstance(v, (dict, list)) and not (isinstance(v, dict) and ignorar_filho(v)):
            achadas += condicoes(v, prof + 1)
    return achadas


def aplica_condicoes(o: Oferta, obj) -> Oferta:
    """Usa o pagamento do mesmo preço que virou a oferta (o PIX entra como preço, se for menor)."""
    candidatas = [c for c in condicoes(obj) if abs(c["base"] - o.preco) < 0.01]
    if not candidatas:
        return o
    c = min(candidatas, key=lambda c: (c["pix"] or c["base"], -(c["parcelas"] or 0)))
    if c["pix"] and c["pix"] < o.preco:
        o.preco, o.forma = c["pix"], "no PIX"
    elif c["parcelas"]:
        o.forma = "à vista"
    o.parcelas, o.parcela, o.sem_juros, o.total = c["parcelas"], c["parcela"], c["sem_juros"], c["total"]
    return o


def pagamento_do_texto(o: Oferta, t: str, perto: int | None = None) -> Oferta:
    """Amazon: "10% off à vista no Pix ... ou em até 12x de R$ 391,62 sem juros (total parcelado R$ ...)".

    `perto` limita a busca ao começo do trecho (logo depois do preço principal), para não pegar o
    parcelamento de outro produto da página; o "sem juros" pode ser confirmado mais adiante.
    """
    t = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", t)).split())
    regiao = t[:perto] if perto else t
    if re.search(r"(?i)à vista no pix", regiao):
        o.forma = "no PIX"
    padrao = r"(?i)em até (\d{1,2})x de R\$\s*([\d.]+,\d{2})(?:/mês)?(?:\s*R\$\s*[\d.]+,\d{2})?(\s*sem juros)?"
    achados = list(re.finditer(padrao, regiao))
    m = next((x for x in achados if x.group(3)), achados[0] if achados else None)
    if m and int(m.group(1)) >= 2:
        o.parcelas, o.parcela = int(m.group(1)), para_numero(m.group(2))
        confirma = rf"{o.parcelas}x de R\$\s*{re.escape(m.group(2))}(?:/mês)?(?:\s*R\$\s*[\d.]+,\d{{2}})?\s*sem juros"
        o.sem_juros = True if (m.group(3) or re.search(confirma, t, re.I)) else None
        tot = re.search(rf"{o.parcelas}x de R\$\s*{re.escape(m.group(2))}[^()]{{0,80}}\(total parcelado R\$\s*([\d.]+,\d{{2}})\)", t)
        o.total = para_numero(tot.group(1)) if tot else None
    return o


def varre_skus(obj: dict, fonte: dict, saida: list[Oferta]) -> bool:
    """Produto VTEX (Samsung, Fast Shop, drogarias...): cada SKU (50/100 ml, 127/220 V) vira uma oferta própria,
    com o nome do SKU no título, para o filtro de tamanho/voltagem valer e não misturar preços."""
    itens = obj.get("items")
    base = nome_de(obj)
    if not (base and isinstance(itens, list) and itens and all(isinstance(i, dict) and "sellers" in i for i in itens)):
        return False
    for it in itens:
        completo = str(it.get("nameComplete") or "").strip()
        titulo = completo if normaliza(base)[:20] in normaliza(completo) else f"{base} {it.get('name') or ''}".strip()
        titulo = " ".join(html.unescape(titulo).split())
        if not (bate_modelo(titulo) and cor_ok(titulo)) or excluido(titulo):
            continue
        precos = precos_de(it)
        if precos:
            saida.append(aplica_condicoes(Oferta(titulo[:120], min(precos), fonte["nome"],
                                                 url_de(obj, fonte["url"]), fonte["nome"]), it))
    return True


def varre(obj, fonte: dict, saida: list[Oferta], prof: int = 0) -> None:
    if prof > 80:
        return
    if isinstance(obj, dict) and varre_skus(obj, fonte, saida):
        return
    if isinstance(obj, dict):
        titulo = nome_de(obj)
        if (titulo and bate_modelo(titulo) and cor_ok(titulo) and not excluido(titulo)
                and not indisponivel(obj)):
            precos = precos_de(obj)
            if precos:
                saida.append(aplica_condicoes(Oferta(
                    titulo=" ".join(html.unescape(titulo).split())[:120],
                    preco=min(precos),
                    loja=loja_de(obj) or fonte["nome"],
                    url=url_de(obj, fonte["url"]),
                    fonte=fonte["nome"],
                ), obj))
        for v in obj.values():
            if isinstance(v, (dict, list)):
                varre(v, fonte, saida, prof + 1)
    elif isinstance(obj, list):
        for v in obj:
            if isinstance(v, (dict, list)):
                varre(v, fonte, saida, prof + 1)


def blocos_json(texto: str):
    """Acha os dados estruturados que as lojas embutem nas páginas."""
    inicio = texto.lstrip()[:1]
    if inicio in ("[", "{"):  # resposta de API (ex.: VTEX)
        try:
            yield json.loads(texto)
            return
        except ValueError:
            pass
    for m in re.finditer(r"<script[^>]*type=[\"']application/(?:ld\+)?json[\"'][^>]*>(.*?)</script>",
                         texto, re.S | re.I):
        bruto = m.group(1).strip()
        for tentativa in (bruto, html.unescape(bruto)):
            try:
                yield json.loads(tentativa)
                break
            except ValueError:
                continue
    dec = json.JSONDecoder()
    for m in re.finditer(r"(?:window\.)?__[A-Z][A-Z0-9_]*__\s*=\s*", texto):
        i = m.end()
        if texto[i:i + 1] in ("{", "["):
            try:
                yield dec.raw_decode(texto, i)[0]
            except ValueError:
                pass
    pedacos = []  # Next.js (App Router) manda os dados em pedaços
    for m in re.finditer(r'self\.__next_f\.push\(\[1,\s*"((?:[^"\\]|\\.)*)"\]\)', texto, re.S):
        try:
            pedacos.append(json.loads('"' + m.group(1) + '"'))
        except ValueError:
            pass
    for linha in "".join(pedacos).split("\n"):
        _, sep, resto = linha.partition(":")
        if sep and resto[:1] in ("{", "["):
            try:
                yield json.loads(resto)
            except ValueError:
                pass


def varre_texto(texto: str, fonte: dict) -> list[Oferta]:
    """Plano B quando a página não tem dados estruturados: preço logo após o nome."""
    t = html.unescape(texto).replace('\\"', '"').replace("\\u002F", "/")
    t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t))
    padrao = re.compile("|".join(re.escape(k) for k in CFG["palavras_chave"]), re.I)
    proximo_produto = re.compile(r'"(?:title|name|productName)"\s*:', re.I)
    preco_re = re.compile(
        r'"(?:price|bestPrice|salePrice|lowPrice|spotPrice|priceValue|priceAmount)"\s*:\s*"?(\d[\d.,]*)'
        r'|"current_price"\s*:\s*\{\s*"value"\s*:\s*(\d+(?:\.\d+)?)'
        r"|R\$\s*(\d{1,3}(?:\.\d{3})+(?:\s*,\s*\d{2})?)", re.I)
    ofertas = []
    for m in list(padrao.finditer(t))[:30]:
        trecho = t[max(0, m.start() - 150): m.end() + 150]
        if excluido(trecho) or not cor_ok(trecho):
            continue
        fim = m.end() + 1200
        prox = proximo_produto.search(t, m.end() + 20, fim)
        if prox:
            fim = prox.start()
        precos = [p for pm in preco_re.finditer(t, m.end(), fim)
                  if (p := no_intervalo(next(g for g in pm.groups() if g).replace(" ", ""))) is not None]
        if precos:
            ofertas.append(Oferta(f"{CFG['produto']} ({fonte['nome']})", min(precos), fonte["nome"],
                                  fonte["url"], fonte["nome"], estimado=True))
    return ofertas


class Bloqueado(Exception):
    pass


DEPURAR = bool(os.getenv("DEPURAR"))
IMITACOES = ["chrome", "safari", "firefox"] if IMITAR else [None]


def baixa(url: str) -> tuple[str, str]:
    """Baixa a página (seguindo redirecionamentos). Se a loja bloquear, tenta com outro navegador."""
    ultimo_erro = None
    for tentativa, imitar in enumerate(IMITACOES):
        try:
            extra = {"impersonate": imitar} if imitar else {}
            r = navegador.get(url, headers=CABECALHOS, timeout=30, allow_redirects=True, **extra)
            texto = r.text
            if r.status_code in (403, 429, 503):
                if DEPURAR:
                    print(f"          [diag] {imitar}: HTTP {r.status_code} em {r.url} :: {resumo_html(texto)}")
                raise Bloqueado(f"HTTP {r.status_code} (a loja bloqueou o robô)")
            if r.status_code >= 400:
                raise RuntimeError(f"HTTP {r.status_code}")
            baixo = texto[:20000].lower()
            if not bate_modelo(texto) and any(x in baixo for x in SINAIS_DE_BLOQUEIO):
                if DEPURAR:
                    print(f"          [diag] {imitar}: anti-robô em {r.url} :: {resumo_html(texto)}")
                raise Bloqueado("página de verificação anti-robô")
            return texto, str(r.url)
        except Exception as e:  # noqa: BLE001
            ultimo_erro = e
            time.sleep(2 + tentativa * 3)
    raise ultimo_erro  # type: ignore[misc]


def resumo_html(texto: str, n: int = 220) -> str:
    titulo = re.search(r"<title[^>]*>(.*?)</title>", texto, re.S | re.I)
    corpo = " ".join(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style).*?</\1>", " ", texto)).split())
    return f"title={html.unescape(titulo.group(1).strip())[:80]!r} corpo={html.unescape(corpo)[:n]!r}" if titulo \
        else f"corpo={html.unescape(corpo)[:n]!r}"


def amazon(texto: str, fonte: dict, url_final: str) -> list[Oferta]:
    """Página de produto da Amazon: título em #productTitle e preço no bloco principal."""
    m = re.search(r'id="productTitle"[^>]*>(.*?)</span>', texto, re.S)
    if not m:
        return []
    titulo = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", m.group(1))).split())
    if not (bate_modelo(titulo) and cor_ok(titulo)) or excluido(titulo):
        if DEPURAR:
            print(f"          [diag] título fora do filtro (cor/voltagem): {titulo[:120]!r}")
        return []
    for marcador in ("corePriceDisplay_desktop_feature_div", "corePrice_feature_div", "apex_desktop",
                     "corePrice_desktop", "priceblock_ourprice", "price_inside_buybox"):
        i = texto.find(marcador)
        if i < 0:
            continue
        trecho = html.unescape(texto[i:i + 25000])
        pm = re.search(r'class="a-offscreen">\s*R\$\s*([\d.]+,\d{2})', trecho) or \
            re.search(r'"priceAmount"\s*:\s*([\d.]+)', trecho)
        if pm:
            p = no_intervalo(pm.group(1))
            if p is not None:
                url_limpa = re.sub(r"(/dp/[A-Z0-9]{10}).*", r"\1", url_final)
                return [pagamento_do_texto(Oferta(titulo[:120], p, "Amazon", url_limpa, fonte["nome"]),
                                           texto[i:], perto=1500)]  # o "sem juros" às vezes vem mais abaixo
    if DEPURAR:
        print("          [diag] Amazon: achei o título mas não o preço principal (sem estoque?)")
    return []


def amazon_busca(texto: str, fonte: dict) -> list[Oferta]:
    """Busca da Amazon: lê cada anúncio separado (título + preço principal do card)."""
    ofertas = []
    for card in re.split(r'data-component-type="s-search-result"', texto)[1:]:
        card = html.unescape(card[:40000])
        titulos = re.findall(r'<h2[^>]*aria-label="([^"]+)"', card) or \
            [re.sub(r"<[^>]+>", " ", t) for t in re.findall(r"<h2[^>]*>(.*?)</h2>", card, re.S)]
        titulo = " ".join(" ".join(titulos).split())
        if not titulo or not bate_modelo(titulo):
            continue
        pm = re.search(r'class="a-offscreen">\s*R\$\s*([\d.]+,\d{2})', card)
        p = no_intervalo(pm.group(1)) if pm else None
        filtro_ok = cor_ok(titulo) and not excluido(titulo)
        if DEPURAR:
            print(f"          [diag] card: {'ok ' if filtro_ok else 'fora'} {brl(p) if p else 'sem preço'} | {titulo[:110]}")
        if p is None or not filtro_ok:
            continue
        asin = re.search(r"/dp/([A-Z0-9]{10})", card)
        url = f"https://www.amazon.com.br/dp/{asin.group(1)}" if asin else fonte["url"]
        ofertas.append(pagamento_do_texto(Oferta(titulo[:120], p, "Amazon", url, fonte["nome"]), card))
    return ofertas


REFERENCIA: dict = {}  # mínima/máxima histórica (Promobit), preenchida pela fonte "promobit_produto"


def promobit_produto(texto: str, fonte: dict, url_final: str) -> list[Oferta]:
    """Página do produto no Promobit (ex.: /oferta/perfume-azzaro-wanted-edt-masculino-100ml/).

    Traz o histórico de preço dos posts (menor e maior preço já postados) e o post mais recente. O post só conta
    como preço atual se for recente (`max_horas`), porque oferta de dias atrás quase sempre já acabou.
    """
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', texto, re.S)
    if not m:
        raise RuntimeError("página do Promobit sem dados (layout mudou?)")
    oferta = ((json.loads(m.group(1)).get("props") or {}).get("pageProps") or {}).get("serverOffer") or {}
    ref = oferta.get("referencePrices") or {}
    if para_numero(ref.get("minPrice")):
        REFERENCIA.update(minima=para_numero(ref["minPrice"]), maxima=para_numero(ref.get("maxPrice")),
                          fonte="Promobit")
    titulo = " ".join(str(oferta.get("offerTitle") or "").split())
    preco = no_intervalo(oferta.get("offerPrice"))
    publicado = oferta.get("offerPublished")
    try:
        idade = datetime.now(BRT) - datetime.fromisoformat(re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", publicado))
    except (TypeError, ValueError):
        idade = None
    recente = idade is not None and idade <= timedelta(hours=fonte.get("max_horas", 24))
    if DEPURAR:
        print(f"          [diag] Promobit: mínima {REFERENCIA.get('minima')} / máxima {REFERENCIA.get('maxima')} | "
              f"último post {preco} há {idade} | {titulo[:70]}")
    if not (titulo and preco and recente and bate_modelo(titulo) and cor_ok(titulo)) or excluido(titulo):
        return []
    loja = oferta.get("storeName") or oferta.get("storeDomain") or "Promobit"
    horas = int(idade.total_seconds() // 3600)
    return [Oferta(f"{titulo[:100]} (post no Promobit há {horas}h)", preco, str(loja), url_final, fonte["nome"])]


def consulta_fonte(fonte: dict) -> list[Oferta]:
    texto, url_final = baixa(fonte["url"])
    if fonte.get("tipo") == "promobit_produto":
        return promobit_produto(texto, fonte, url_final)
    ofertas: list[Oferta] = []
    if "amazon.com" in url_final:
        ofertas = amazon_busca(texto, fonte) if "s-search-result" in texto else amazon(texto, fonte, url_final)
        if not ofertas:  # a página da Amazon foi lida, mas nada passou no filtro: não chutar preço
            if not bate_modelo(texto):
                raise RuntimeError("a página não menciona o modelo (busca vazia ou layout mudou)")
            return []
    if not ofertas:
        for bloco in blocos_json(texto):
            varre(bloco, fonte, ofertas)
    if not ofertas:
        ofertas = varre_texto(texto, fonte)
    if DEPURAR and not ofertas:
        diagnostico(texto, url_final)
    if not ofertas and not bate_modelo(texto):
        raise RuntimeError("a página não menciona o modelo (busca vazia ou layout mudou)")
    if fonte.get("trocar_link"):
        de, para = fonte["trocar_link"]
        for o in ofertas:
            o.url = o.url.replace(de, para)
    if fonte.get("desconto_pix"):  # loja que só informa o preço cheio, mas dá desconto fixo no PIX
        for o in ofertas:
            o.preco = round(o.preco * (1 - fonte["desconto_pix"] / 100), 2)
            o.forma = "no PIX"
    return ofertas


def diagnostico(texto: str, url_final: str) -> None:
    """Só nos testes de pull request: mostra no log por que uma página não rendeu preço."""
    blocos = list(blocos_json(texto))
    print(f"          [diag] url final: {url_final} | {len(texto)} bytes | {len(blocos)} blocos JSON")
    print(f"          [diag] {resumo_html(texto, 160)}")
    limpo = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", texto)).split())
    padrao = re.compile("|".join(re.escape(k) for k in CFG["palavras_chave"]), re.I)
    for m in list(padrao.finditer(limpo))[:4]:
        print(f"          [diag] ...{limpo[max(0, m.start() - 120): m.end() + 260]!r}")
    for m in list(re.finditer(r'"[A-Za-z_]*(?:price|preco)[A-Za-z_]*"\s*:', texto, re.I))[:3]:
        print(f"          [diag] chave de preço: {texto[m.start(): m.start() + 140]!r}")


def sem_repetidas(ofertas: list[Oferta]) -> list[Oferta]:
    # mesmo preço visto em lugares diferentes: fica o mais específico (com loja e link próprios)
    # (entre repetidas, fica a que sabe como pagar: PIX/parcelas). Ordena pelo custo de verdade.
    vistas, unicas = set(), []
    for o in sorted(ofertas, key=lambda o: (o.preco, o.estimado, not o.parcelas, not o.forma,
                                            o.loja == o.fonte, o.url in URLS_FONTES)):
        chave = o.preco
        if chave not in vistas:
            vistas.add(chave)
            unicas.append(o)
    return sorted(unicas, key=lambda o: (o.custo, o.estimado))


# -------------------------------------------------------------------- mensagens
def negrito(t: str, canal: str) -> str:
    return {"telegram": f"<b>{html.escape(t, quote=False)}</b>", "discord": f"**{t}**"}.get(canal, f"*{t}*")


def texto(t: str, canal: str) -> str:
    return html.escape(t, quote=False) if canal == "telegram" else t


def link(t: str, url: str, canal: str) -> str:
    if canal == "telegram":
        return f'<a href="{html.escape(url)}">{html.escape(t, quote=False)}</a>'
    if canal == "discord":
        return f"[{t}](<{url}>)"
    return f"{t}: {url}"


def monta_mensagem(cabecalho: str, ofertas: list[Oferta], notas: list[str], canal: str) -> str:
    linhas = [negrito(cabecalho, canal), ""]
    for o in ofertas[:5]:
        aviso = " ⚠️ estimado, confira" if o.estimado else ""
        forma = f" {o.forma}" if o.forma else ""
        linhas.append(f"• {negrito(brl(o.preco), canal)}{texto(forma, canal)} — {link(o.loja, o.url, canal)}"
                      f"{texto(aviso, canal)}")
        if o.parcelas:
            linhas.append("  " + texto(linha_parcelado(o), canal))
        linhas.append(f"  {texto(o.titulo, canal)}")
    if not ofertas:
        linhas.append(texto("Nenhum preço encontrado nesta rodada.", canal))
    if notas:
        linhas.append("")
        linhas += [texto(n, canal) for n in notas]
    return "\n".join(linhas)


def linha_parcelado(o: Oferta) -> str:
    partes = f"ou {o.parcelas}x de {brl(o.parcela)}{' sem juros' if o.sem_juros else ''} = {brl(o.total_parcelado)}"
    if o.parcelado_menor:
        partes += " ✅ parcelado sai mais barato"
    return partes


def envia_grupo(cabecalho: str, ofertas: list[Oferta], notas: list[str]) -> None:
    """Promoção boa de um produto com "no_grupo": também vai para o grupo do caçador (só o aviso da oferta;
    'comecei a acompanhar', resumo e avisos técnicos continuam só no privado)."""
    token, grupo = os.getenv("TELEGRAM_TOKEN"), os.getenv("TELEGRAM_CHAT_ID_CACADOR")
    cabecalho = cabecalho.replace("no seu preço-alvo", "no preço-alvo")
    if SIMULAR or not (token and grupo):
        if SIMULAR:
            print("\n[simulação] no grupo, a mensagem seria:\n")
            print(monta_mensagem(cabecalho, ofertas, notas, "whatsapp"))
        else:
            print("[grupo] sem TELEGRAM_CHAT_ID_CACADOR: o aviso ficou só no privado")
        return
    corpo = {"chat_id": grupo, "parse_mode": "HTML", "disable_web_page_preview": True,
             "text": monta_mensagem(cabecalho, ofertas, notas, "telegram")}
    try:
        for _ in range(2):
            r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=20, json=corpo)
            novo_id = (r.json().get("parameters") or {}).get("migrate_to_chat_id") if r.status_code == 400 else None
            if not novo_id:
                break
            # o Telegram troca o ID quando o grupo vira "supergrupo" (ex.: ao mudar permissões); manda para o
            # novo sem mostrar o número no log, que é público
            print("[aviso] o grupo mudou de ID (virou supergrupo). Rode o modo 'grupo' do caçador e atualize "
                  "o secret TELEGRAM_CHAT_ID_CACADOR.")
            corpo["chat_id"] = novo_id
        r.raise_for_status()
        print(f"[enviado] grupo do Telegram: {cabecalho}")
    except Exception as e:  # noqa: BLE001
        print(f"[erro] grupo do Telegram: {e} {erro_telegram(e)}")


def erro_telegram(e: Exception) -> str:
    """Só a descrição do erro (a resposta completa pode trazer o ID do grupo, e o log é público)."""
    resposta = getattr(e, "response", None)
    if resposta is None:
        return ""
    try:
        return resposta.json().get("description", "")
    except ValueError:
        return resposta.text[:200]


def envia(cabecalho: str, ofertas: list[Oferta], notas: list[str]) -> list[str]:
    if SIMULAR:
        print("\n[simulação] a mensagem seria:\n")
        print(monta_mensagem(cabecalho, ofertas, notas, "whatsapp"))
        return []
    enviados = []
    token, chat = os.getenv("TELEGRAM_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if token and chat:
        try:
            r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=20, json={
                "chat_id": chat, "parse_mode": "HTML", "disable_web_page_preview": True,
                "text": monta_mensagem(cabecalho, ofertas, notas, "telegram")})
            r.raise_for_status()
            enviados.append("Telegram")
        except Exception as e:  # noqa: BLE001
            print(f"[erro] Telegram: {e} {erro_telegram(e)}")
    webhook = os.getenv("DISCORD_WEBHOOK")
    if webhook:
        try:
            requests.post(webhook, timeout=20, json={
                "content": monta_mensagem(cabecalho, ofertas, notas, "discord")[:1990]}).raise_for_status()
            enviados.append("Discord")
        except Exception as e:  # noqa: BLE001
            print(f"[erro] Discord: {e}")
    fone, apikey = os.getenv("WHATSAPP_PHONE"), os.getenv("WHATSAPP_APIKEY")
    if fone and apikey:  # via CallMeBot (serviço gratuito, não oficial)
        try:
            msg = quote_plus(monta_mensagem(cabecalho, ofertas, notas, "whatsapp"))
            requests.get(f"https://api.callmebot.com/whatsapp.php?phone={fone}&text={msg}&apikey={apikey}",
                         timeout=30).raise_for_status()
            enviados.append("WhatsApp")
        except Exception as e:  # noqa: BLE001
            print(f"[erro] WhatsApp: {e}")
    if enviados:
        print(f"[enviado] {', '.join(enviados)}: {cabecalho}")
    if not (token and chat) and not webhook and not (fone and apikey):
        print("\n[simulação] nenhum canal configurado; a mensagem seria:\n")
        print(monta_mensagem(cabecalho, ofertas, notas, "whatsapp"))
    return enviados


# ----------------------------------------------------------------------- estado
def carrega_estado() -> dict:
    try:
        return json.loads(ARQ_ESTADO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def salva_estado(estado: dict) -> None:
    ARQ_ESTADO.parent.mkdir(parents=True, exist_ok=True)
    ARQ_ESTADO.write_text(json.dumps(estado, ensure_ascii=False, indent=1), encoding="utf-8")


# ------------------------------------------------------------------- cupons (Promobit)
CUPOM_SLUG = {  # nome da loja (normalizado) -> página de cupons no Promobit
    "epoca cosmeticos": "epoca-cosmeticos", "drogarias pacheco": "drogarias-pacheco",
    "drogaria pacheco": "drogarias-pacheco", "extrafarma": "extrafarma", "americanas": "americanas",
    "webcontinental": "webcontinental", "mercado livre": "mercado-livre", "amazon": "amazon", "sephora": "sephora",
    "beleza na web": "beleza-na-web", "drogasil": "drogasil", "droga raia": "droga-raia",
}
RESTRICAO = re.compile(r"(?i)selecionad|participante|marca|linha |categoria|kit|preservativ|primeira compra|"
                       r"1ª compra|app|frete|mimo|brinde|campanha")
_cache_cupons: dict[str, list[dict]] = {}


def cupons_da_loja(slug: str, dias: int = 45) -> list[dict]:
    """Cupons ativos de uma loja no Promobit (só os aprovados e publicados/verificados há até `dias`)."""
    if slug in _cache_cupons:
        return _cache_cupons[slug]
    texto, _ = baixa(f"https://www.promobit.com.br/cupons/loja/{slug}/")
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', texto, re.S)
    achados: list[dict] = []

    def anda(x, prof=0):
        if prof > 12:
            return
        if isinstance(x, dict):
            if (x.get("couponId") and x.get("couponStatusName", "APPROVED") == "APPROVED"
                    and x.get("storeSlug", slug) == slug):  # a página também lista cupons de outras lojas
                achados.append(x)
            for v in x.values():
                anda(v, prof + 1)
        elif isinstance(x, list):
            for v in x[:200]:
                anda(v, prof + 1)

    if m:
        anda(json.loads(m.group(1)))
    limite = datetime.now(BRT) - timedelta(days=dias)

    def data(c):
        for k in ("couponVerified", "couponPublished"):
            try:
                return datetime.fromisoformat(re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", c.get(k) or ""))
            except ValueError:
                continue
        return None

    vistos, cupons = set(), []
    for c in sorted(achados, key=lambda c: data(c) or limite, reverse=True):
        d, codigo = data(c), (c.get("couponCode") or "").strip()
        if not codigo or codigo in vistos or (d and d < limite):
            continue
        vistos.add(codigo)
        texto_cupom = f"{c.get('couponTitle') or ''} {limpa(c.get('couponInstructions'))}"
        pct = re.search(r"(\d{1,2})\s*%", c.get("couponDiscountShort") or c.get("couponDiscount") or "")
        minimo = re.search(r"(?i)acima de R\$\s*([\d.]+(?:,\d{2})?)", texto_cupom)
        cupons.append({"codigo": codigo, "desconto": c.get("couponDiscountShort") or c.get("couponDiscount") or "",
                       "detalhe": limpa(c.get("couponInstructions"))[:90] or str(c.get("couponTitle") or "")[:90],
                       "pct": int(pct.group(1)) if pct else None,
                       "minimo": para_numero(minimo.group(1)) if minimo else None,
                       "geral": not RESTRICAO.search(texto_cupom)})
    _cache_cupons[slug] = cupons
    return cupons


def limpa(t) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", str(t or ""))).split())


def notas_cupom(o: Oferta | None, maximo: int = 3) -> list[str]:
    """Para a melhor oferta: cupons ativos da loja e o possível preço com o cupom geral (conferir no carrinho)."""
    if not (o and CFG.get("mostrar_cupons")):
        return []
    fonte = next((f for f in CFG["fontes"] if f["nome"] == o.fonte), {})
    slug = fonte.get("cupons_promobit") or CUPOM_SLUG.get(normaliza(o.loja).replace("(no pix)", "").strip())
    if not slug:
        return []
    try:
        cupons = cupons_da_loja(slug)
    except Exception as e:  # noqa: BLE001  (cupom é extra; não atrapalha o alerta)
        print(f"[cupons] {slug}: {str(e)[:80]}")
        return []
    if not cupons:
        return []
    linhas = [f"🎟️ Cupons ativos na {o.loja} (Promobit; confira no carrinho se valem para o produto):"]
    for c in cupons[:maximo]:
        linha = f"• {c['codigo']} — {c['desconto']}: {c['detalhe']}"
        if c["geral"] and c["pct"] and (not c["minimo"] or c["minimo"] <= o.preco):
            linha += f" → ~{brl(round(o.preco * (1 - c['pct'] / 100), 2))}"
        linhas.append(linha)
    return linhas


def linha_referencia() -> list[str]:
    if not REFERENCIA.get("minima"):
        return []
    maxima = f", máxima {brl(REFERENCIA['maxima'])}" if REFERENCIA.get("maxima") else ""
    return [f"Histórico ({REFERENCIA.get('fonte')}): mínima {brl(REFERENCIA['minima'])}{maxima}"]


def decide(estado: dict, melhor: Oferta | None, agora: datetime) -> tuple[str | None, list[str]]:
    """Devolve (motivo do alerta ou None, notas) e atualiza o estado."""
    notas: list[str] = []
    historico = [h for h in estado.get("historico", [])
                 if datetime.fromisoformat(h[0]) > agora - timedelta(days=14)]
    if melhor is None:
        estado["historico"] = historico
        return None, notas

    recentes = [p for q, p in historico if datetime.fromisoformat(q) > agora - timedelta(days=3)]
    mediana = statistics.median(recentes) if len(recentes) >= 6 else None
    recorde = estado.get("menor_ja_visto")
    custo = melhor.custo
    if recorde is None or custo < recorde["preco"]:
        if recorde is not None:
            notas.append(f"📉 Menor preço já visto pelo alerta (antes: {brl(recorde['preco'])}).")
        estado["menor_ja_visto"] = {"preco": custo, "quando": agora.isoformat(), "loja": melhor.loja}

    motivo = None
    alvo = CFG.get("preco_alvo")
    queda = CFG.get("avisar_queda_percentual")
    minima = REFERENCIA.get("minima") if CFG.get("alvo_minima_historica") else None
    if minima and custo <= minima:
        jeito = f" {melhor.forma}" if melhor.forma else ""
        motivo = (f"🏆 {CFG['produto']} bateu a mínima histórica{jeito}: {brl(custo)} "
                  f"(a menor do {REFERENCIA.get('fonte')} era {brl(minima)})!")
    elif alvo and custo <= alvo:
        jeito = " parcelado" if melhor.parcelado_menor else (f" {melhor.forma}" if melhor.forma else "")
        motivo = f"🔥 {CFG['produto']} chegou no seu preço-alvo{jeito} ({brl(alvo)})!"
    elif queda and mediana and not melhor.estimado and custo <= mediana * (1 - queda / 100):
        pct = (1 - custo / mediana) * 100
        motivo = f"📉 {CFG['produto']} caiu {pct:.0f}% (média dos últimos dias: {brl(mediana)})"

    ultimo = estado.get("ultimo_alerta")
    if motivo:
        repetir = timedelta(hours=CFG.get("repetir_alerta_horas", 6))
        novo = (ultimo is None or custo < ultimo["preco"] - 0.5
                or agora - datetime.fromisoformat(ultimo["quando"]) >= repetir)
        if novo:
            estado["ultimo_alerta"] = {"preco": custo, "quando": agora.isoformat()}
        else:
            motivo = None
    else:
        estado["ultimo_alerta"] = None  # voltou a subir: a próxima queda avisa de novo

    historico.append([agora.isoformat(), custo])
    estado["historico"] = historico[-2000:]
    return motivo, notas


# ------------------------------------------------------------------------- main
SIMULAR = False


def main() -> int:
    global SIMULAR
    modo = (sys.argv[1] if len(sys.argv) > 1 else "verificar").lower()
    if modo == "simulacao":
        SIMULAR, modo = True, "teste"
    agora = datetime.now(BRT)
    estado = carrega_estado()
    # mudou modelo/cor/voltagem? o histórico antigo não vale mais para comparar quedas
    filtro = json.dumps([CFG["palavras_chave"], CFG.get("cores_aceitas"), CFG.get("voltagem")])
    comecando = estado.get("filtro") != filtro  # produto novo (ou filtro mudou): avisa uma vez
    if comecando:
        estado = {"filtro": filtro}

    ofertas: list[Oferta] = []
    falhas: list[str] = []
    fontes = [f for f in CFG["fontes"] if f.get("ativa", True)]
    if DEPURAR:  # nos pull requests, testa também as desativadas para ver se voltaram a funcionar
        fontes += [dict(f, nome=f["nome"] + " [desativada]") for f in CFG["fontes"] if not f.get("ativa", True)]
    for i, fonte in enumerate(fontes):
        if i:
            time.sleep(random.uniform(1.5, 4))
        try:
            achadas = consulta_fonte(fonte)
            ofertas += achadas
            resumo = ", ".join(f"{brl(o.preco)}{'*' if o.estimado else ''}" for o in
                               sorted(achadas, key=lambda o: o.preco)[:4]) or "nenhum preço"
            print(f"[ok]    {fonte['nome']}: {resumo}")
            for o in sorted(achadas, key=lambda o: o.preco)[:4]:
                pag = f" {o.forma}" if o.forma else ""
                pag += f" | {linha_parcelado(o)}" if o.parcelas else ""
                print(f"          {brl(o.preco)}{pag} | {o.loja} | {o.titulo[:70]} | {o.url[:90]}")
        except Exception as e:  # noqa: BLE001
            erro = str(e).split(". See ")[0].replace("Failed to perform, ", "")
            falhas.append(f"{fonte['nome']}: {erro[:80]}")
            print(f"[falha] {fonte['nome']}: {erro}")

    ofertas = sem_repetidas(ofertas)
    melhor = ofertas[0] if ofertas else None
    motivo, notas = decide(estado, melhor, agora)
    if melhor:
        jeito = f" (parcelado; à vista {brl(melhor.preco)})" if melhor.parcelado_menor else \
            (f" {melhor.forma}" if melhor.forma else "")
        print(f"\nMelhor preço: {brl(melhor.custo)}{jeito} em {melhor.loja}")
    else:
        print("\nMelhor preço: nenhum")

    if ofertas:
        estado["falhas_seguidas"] = 0
    else:
        estado["falhas_seguidas"] = estado.get("falhas_seguidas", 0) + 1

    rodape = [f"Páginas lidas: {len(fontes) - len(falhas)}/{len(fontes)}"]
    # leu páginas mas nada passou no filtro: não é bloqueio, é que não há anúncio do jeito pedido
    leu_sem_anuncio = not ofertas and len(falhas) < len(fontes)
    if leu_sem_anuncio:
        rodape.append("As páginas abriram, mas nenhum anúncio bateu com o modelo, a voltagem "
                      f"({CFG.get('voltagem') or 'qualquer'}) e a faixa de preço.")
    hoje = agora.date().isoformat()

    cupons = notas_cupom(melhor) if (modo == "teste" or motivo or comecando) else []
    if modo == "teste":
        envia(f"🧪 Teste do alerta — {CFG['produto']}", ofertas,
              notas + cupons + linha_referencia() + rodape + falhas)
    elif motivo:
        envia(motivo, ofertas, notas + cupons + linha_referencia() + rodape)
        if CFG.get("no_grupo"):
            envia_grupo(motivo, ofertas[:3], notas + cupons + linha_referencia())
    elif comecando:
        alvo = [f"Alvo: {brl(CFG['preco_alvo'])}"] if CFG.get("preco_alvo") else []
        alvo += linha_referencia()
        envia(f"✅ Comecei a acompanhar — {CFG['produto']}", ofertas, alvo + cupons + rodape + falhas)
    elif (CFG.get("resumo_diario_hora") is not None and agora.hour >= CFG["resumo_diario_hora"]
          and estado.get("ultimo_resumo") != hoje):
        recorde = estado.get("menor_ja_visto")
        extra = [f"Menor já visto: {brl(recorde['preco'])} ({recorde['loja']})"] if recorde else []
        envia(f"📊 Resumo diário — {CFG['produto']}", ofertas,
              extra + ([f"Alvo: {brl(CFG['preco_alvo'])}"] if CFG.get("preco_alvo") else [])
              + linha_referencia() + rodape + falhas)
        estado["ultimo_resumo"] = hoje
    elif estado["falhas_seguidas"] == 3:
        problema = "nenhum anúncio do jeito pedido" if leu_sem_anuncio else "não consegui ler nenhuma loja"
        envia(f"⚠️ {CFG['produto']}: {problema} nas últimas 3 verificações",
              [], rodape + falhas)
    else:
        print("[sem aviso] preço acima do alvo, sem queda brusca, e o resumo de hoje já foi enviado")

    salva_estado(estado)
    return 0


if __name__ == "__main__":
    sys.exit(main())
