# Alerta de promoção — Samsung Lava e Seca WD13FG

Robô que roda de graça no GitHub Actions a cada 20 minutos, lê o preço da WD13FG em várias lojas
(versões inox e black; via Buscapé e Zoom, que comparam várias lojas, além de Samsung Shop, Fast Shop e Mercado Livre) e te avisa
no **Telegram** (e opcionalmente Discord/WhatsApp) quando:

- o menor preço chega no **preço-alvo** (`preco_alvo` no `config.json`), ou
- o preço **cai de repente** (padrão: 7% abaixo da média dos últimos 3 dias).

Todo dia, a partir das 9h, ele manda um **resumo** com os menores preços: se o resumo parar de chegar,
o alerta parou.

## Configurar (uns 5 minutos, dá pra fazer pelo celular)

### 1. Criar o bot do Telegram
1. No Telegram, abra o **@BotFather**, mande `/newbot`, escolha um nome e um usuário terminado em `bot`.
2. Ele responde com um **token** (algo como `123456:ABC-...`). Copie.
3. Abra o seu bot novo (o link vem na mesma mensagem) e toque em **Iniciar**. Sem isso ele não pode te mandar mensagem.
4. Abra o **@userinfobot** e mande qualquer coisa: ele responde com o seu **Id** (um número). Copie.

### 2. Colocar os segredos no GitHub
No repositório: **Settings → Secrets and variables → Actions → New repository secret**

| Nome | Valor |
|---|---|
| `TELEGRAM_TOKEN` | o token do BotFather |
| `TELEGRAM_CHAT_ID` | o seu Id do @userinfobot |

### 3. Testar
Aba **Actions → Alerta WD13FG → Run workflow** (modo `teste`). Em ~1 minuto chega uma mensagem no
Telegram com os preços atuais e quais lojas ele conseguiu ler.

## Ajustes (`config.json`)

| Campo | O que faz |
|---|---|
| `preco_alvo` | avisa quando o menor preço ficar igual ou abaixo disso |
| `cores_aceitas` | só considera anúncios que citam uma dessas cores (inox/black); `[]` aceita todas |
| `voltagem` | `"127V"` ignora anúncios que dizem só 220V (e vice-versa); `null` aceita tudo |
| `avisar_queda_percentual` | avisa quedas bruscas mesmo acima do alvo; `null` desliga |
| `repetir_alerta_horas` | se o preço continuar baixo, repete o aviso a cada X horas (ou na hora, se baixar mais) |
| `resumo_diario_hora` | hora do resumo diário (horário de Brasília); `null` desliga |
| `excluir_se_tiver` | palavras que descartam um anúncio (branca, peças, usados, vitrine...) |
| `fontes` | páginas consultadas; dá pra adicionar o link de qualquer produto/busca. `"ativa": false` desliga uma página (Magalu, Casas Bahia, Carrefour e Amazon bloqueiam o GitHub, mas os preços delas já aparecem via Buscapé/Zoom) |

## Canais opcionais

- **Discord:** no servidor, *Configurações do servidor → Integrações → Webhooks → Novo webhook → Copiar URL*.
  Salve como segredo `DISCORD_WEBHOOK`.
- **WhatsApp:** pelo CallMeBot (gratuito, não oficial). Siga as instruções do site callmebot.com para
  liberar seu número e pegar a apikey, e salve os segredos `WHATSAPP_PHONE` (ex.: `5511999999999`) e
  `WHATSAPP_APIKEY`.

## Observações

- Algumas lojas bloqueiam robôs às vezes; o resumo diário mostra quais falharam. Basta uma ou duas
  funcionando (Buscapé/Zoom já comparam várias lojas) para o alerta valer.
- Preço marcado como "estimado" veio de leitura do texto da página: confira no link antes de comprar.
- O GitHub pausa agendamentos de repositórios públicos sem nenhuma atividade por 60 dias. Se acontecer,
  é só reativar na aba Actions.
