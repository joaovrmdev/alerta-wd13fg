#!/usr/bin/env python3
"""
Alerta de promoção da Samsung WD13FG (lava e seca).

Roda no GitHub Actions: lê o preço em várias lojas e manda mensagem no
Telegram (e, se configurado, Discord e WhatsApp) quando o preço chega no alvo
ou cai de repente. Uma vez por dia manda um resumo, que também serve para saber
que o alerta está vivo.

Uso:
    python alerta.py             # verificação normal (o que o agendamento roda)
    python alerta.py teste       # manda um resumo agora, para testar as mensagens
    python alerta.py simulacao   # só mostra no log o que mandaria (usado nos pull requests)
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
CFG = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
ARQ_ESTADO = BASE / "estado" / "estado.json"
BRT = timezone(timedelta(hours=-3))
MIN_VALIDO, MAX_VALIDO = CFG.get("faixa_de_preco_valida", [2500, 15000])
URLS_FONTES = {f["url"] for f in CFG["fontes"]}

CABECALHOS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.6,en;q=0.5",
}
CHAVES_NOME = ("fullName", "name", "title", "productName", "nameComplete", "productTitle", "nome", "titulo")
CHAVES_LOJA = ("storeName", "sellerName", "merchantName", "store", "seller", "merchant",
               "loja", "vendedor", "retailer", "shopName", "shop")
CHAVES_URL = ("url", "link", "href", "productUrl", "permalink", "offerUrl", "canonical")
CHAVE_PRECO = re.compile(
    r"(?i)^(price|lowprice|bestprice|saleprice|spotprice|pixprice|cashprice|finalprice|"
    r"offerprice|currentprice|pricevalue|pricewithdiscount|sellingprice|minprice|"
    r"bestpricevalue|preco|precopix|precoavista|precopromocional)$"
)
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


# ----------------------------------------------------------------- texto e preço
def normaliza(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


MODELOS = [re.sub(r"[\s\-_/]", "", normaliza(k)) for k in CFG["palavras_chave"]]


def bate_modelo(titulo: str) -> bool:
    t = re.sub(r"[\s\-_/]", "", normaliza(titulo))
    return any(m in t for m in MODELOS)


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


def varre(obj, fonte: dict, saida: list[Oferta], prof: int = 0) -> None:
    if prof > 80:
        return
    if isinstance(obj, dict):
        titulo = nome_de(obj)
        if titulo and bate_modelo(titulo) and DEPURAR and (not cor_ok(titulo) or excluido(titulo)):
            print(f"          [diag] fora do filtro (cor/voltagem/palavra): {titulo[:110]}")
        if (titulo and bate_modelo(titulo) and cor_ok(titulo) and not excluido(titulo)
                and not indisponivel(obj)):
            precos = precos_de(obj)
            if precos:
                titulo_limpo = " ".join(html.unescape(titulo).split())[:120]
                cashback = obj.get("fullCashback")
                if isinstance(cashback, str) and obj.get("fullCashbackValue"):
                    titulo_limpo += f" (+{cashback} de cashback)".replace("\xa0", " ")
                if fonte.get("link_produto") and obj.get("id"):
                    url = fonte["link_produto"].format(id=obj["id"])
                else:
                    url = url_de(obj, fonte.get("link_padrao") or fonte["url"])
                saida.append(Oferta(
                    titulo=titulo_limpo,
                    preco=min(precos),
                    loja=loja_de(obj) or fonte["nome"],
                    url=url,
                    fonte=fonte["nome"],
                ))
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


def baixa(url: str, extras: dict | None = None) -> tuple[str, str]:
    """Baixa a página (seguindo redirecionamentos). Se a loja bloquear, tenta com outro navegador."""
    ultimo_erro = None
    for tentativa, imitar in enumerate(IMITACOES):
        try:
            extra = {"impersonate": imitar} if imitar else {}
            r = navegador.get(url, headers={**CABECALHOS, **(extras or {})}, timeout=30, allow_redirects=True, **extra)
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
                return [Oferta(titulo[:120], p, "Amazon", url_limpa, fonte["nome"])]
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
        ofertas.append(Oferta(titulo[:120], p, "Amazon", url, fonte["nome"]))
    return ofertas


def consulta_fonte(fonte: dict) -> list[Oferta]:
    texto, url_final = baixa(fonte["url"], fonte.get("cabecalhos"))
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
    forms = re.findall(r"<form[^>]*>", texto)[:3]
    entradas = re.findall(r"<input[^>]*(?:search|busca|name=)[^>]*>", texto, re.I)[:4]
    links = sorted(set(re.findall(r'href="([^"]*(?:busca|search)[^"]*)"', texto, re.I)))[:6]
    if forms or entradas or links:
        print(f"          [diag] forms={forms} inputs={entradas} links={links}"[:900])
    m0 = re.search(r'"priceValue"\s*:', texto)
    if m0:
        print(f"          [diag] contexto: {texto[max(0, m0.start() - 900): m0.start() + 300]!r}")
    for m in list(re.finditer(r'"[A-Za-z_]*(?:price|preco)[A-Za-z_]*"\s*:', texto, re.I))[:3]:
        print(f"          [diag] chave de preço: {texto[m.start(): m.start() + 140]!r}")


def sem_repetidas(ofertas: list[Oferta]) -> list[Oferta]:
    # mesmo preço visto em lugares diferentes: fica o mais específico (com loja e link próprios)
    vistas, unicas = set(), []
    for o in sorted(ofertas, key=lambda o: (o.preco, o.estimado, o.loja == o.fonte, o.url in URLS_FONTES)):
        chave = o.preco
        if chave not in vistas:
            vistas.add(chave)
            unicas.append(o)
    return unicas


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
        linhas.append(f"• {negrito(brl(o.preco), canal)} — {link(o.loja, o.url, canal)}{texto(aviso, canal)}")
        linhas.append(f"  {texto(o.titulo, canal)}")
    if not ofertas:
        linhas.append(texto("Nenhum preço encontrado nesta rodada.", canal))
    if notas:
        linhas.append("")
        linhas += [texto(n, canal) for n in notas]
    return "\n".join(linhas)


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
            print(f"[erro] Telegram: {e} {getattr(e, 'response', None) and e.response.text}")
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
    if recorde is None or melhor.preco < recorde["preco"]:
        if recorde is not None:
            notas.append(f"📉 Menor preço já visto pelo alerta (antes: {brl(recorde['preco'])}).")
        estado["menor_ja_visto"] = {"preco": melhor.preco, "quando": agora.isoformat(), "loja": melhor.loja}

    motivo = None
    alvo = CFG.get("preco_alvo")
    queda = CFG.get("avisar_queda_percentual")
    if alvo and melhor.preco <= alvo:
        motivo = f"🔥 {CFG['produto']} chegou no seu preço-alvo ({brl(alvo)})!"
    elif queda and mediana and not melhor.estimado and melhor.preco <= mediana * (1 - queda / 100):
        pct = (1 - melhor.preco / mediana) * 100
        motivo = f"📉 {CFG['produto']} caiu {pct:.0f}% (média dos últimos dias: {brl(mediana)})"

    ultimo = estado.get("ultimo_alerta")
    if motivo:
        repetir = timedelta(hours=CFG.get("repetir_alerta_horas", 6))
        novo = (ultimo is None or melhor.preco < ultimo["preco"] - 0.5
                or agora - datetime.fromisoformat(ultimo["quando"]) >= repetir)
        if novo:
            estado["ultimo_alerta"] = {"preco": melhor.preco, "quando": agora.isoformat()}
        else:
            motivo = None
    else:
        estado["ultimo_alerta"] = None  # voltou a subir: a próxima queda avisa de novo

    historico.append([agora.isoformat(), melhor.preco])
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
    if estado.get("filtro") != filtro:
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
                print(f"          {brl(o.preco)} | {o.loja} | {o.titulo[:70]} | {o.url[:90]}")
        except Exception as e:  # noqa: BLE001
            erro = str(e).split(". See ")[0].replace("Failed to perform, ", "")
            falhas.append(f"{fonte['nome']}: {erro[:80]}")
            print(f"[falha] {fonte['nome']}: {erro}")

    ofertas = sem_repetidas(ofertas)
    melhor = ofertas[0] if ofertas else None
    motivo, notas = decide(estado, melhor, agora)
    print(f"\nMelhor preço: {brl(melhor.preco) + ' em ' + melhor.loja if melhor else 'nenhum'}")

    if ofertas:
        estado["falhas_seguidas"] = 0
    else:
        estado["falhas_seguidas"] = estado.get("falhas_seguidas", 0) + 1

    rodape = [f"Páginas lidas: {len(fontes) - len(falhas)}/{len(fontes)}"]
    hoje = agora.date().isoformat()

    if modo == "teste":
        envia(f"🧪 Teste do alerta — {CFG['produto']}", ofertas, notas + rodape + falhas)
    elif motivo:
        envia(motivo, ofertas, notas + rodape)
    elif (CFG.get("resumo_diario_hora") is not None and agora.hour >= CFG["resumo_diario_hora"]
          and estado.get("ultimo_resumo") != hoje):
        recorde = estado.get("menor_ja_visto")
        extra = [f"Menor já visto: {brl(recorde['preco'])} ({recorde['loja']})"] if recorde else []
        envia(f"📊 Resumo diário — {CFG['produto']}", ofertas,
              extra + [f"Alvo: {brl(CFG['preco_alvo'])}"] + rodape + falhas)
        estado["ultimo_resumo"] = hoje
    elif estado["falhas_seguidas"] == 3:
        envia("⚠️ O alerta não conseguiu ler nenhuma loja nas últimas 3 verificações",
              [], falhas)
    else:
        print("[sem aviso] preço acima do alvo, sem queda brusca, e o resumo de hoje já foi enviado")

    salva_estado(estado)
    return 0


if __name__ == "__main__":
    sys.exit(main())
