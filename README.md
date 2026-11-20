# Alerta de promoção — Samsung Lava e Seca WD13FG

Robô que roda de graça no GitHub Actions a cada 30 minutos (disparado pelo cron-job.org, veja
[Disparo](#disparo-cron-joborg)), lê o preço da WD13FG em várias lojas
(versões inox e black; via Buscapé e Zoom, que comparam várias lojas, além de Amazon, Samsung Shop e Fast Shop) e te avisa
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
| `preco_alvo` | avisa quando o menor valor para levar o produto (PIX, à vista ou total parcelado) ficar igual ou abaixo disso |
| `cores_aceitas` | só considera anúncios que citam uma dessas cores (inox/black); `[]` aceita todas |
| `voltagem` | `"220V"` ignora anúncios que dizem só 127V/110V (e vice-versa); `null` aceita tudo |
| `avisar_queda_percentual` | avisa quedas bruscas mesmo acima do alvo; `null` desliga |
| `repetir_alerta_horas` | se o preço continuar baixo, repete o aviso a cada X horas (ou na hora, se baixar mais) |
| `resumo_diario_hora` | hora do resumo diário (horário de Brasília); `null` desliga |
| `excluir_se_tiver` | palavras que descartam um anúncio (branca, peças, usados, vitrine...) |
| `fontes` | páginas consultadas; dá pra adicionar o link de qualquer produto/busca. `"ativa": false` desliga uma página (Magalu, Casas Bahia e Carrefour bloqueiam o GitHub e o Mercado Livre pede login, mas os preços delas já aparecem via Buscapé/Zoom) |

### PIX e parcelado

O alerta lê, quando a loja informa, o preço no PIX e o melhor parcelamento:

- **Samsung, Fast Shop e Loja Electrolux** (VTEX): o valor no PIX e o maior número de parcelas sem juros.
- **Amazon**: o preço principal costuma ser o do PIX ("10% off à vista no Pix") e o parcelamento vem logo abaixo.
- **Buscapé e Zoom**: o preço à vista e o parcelamento da oferta.

O preço-alvo vale para o menor desses valores: o PIX/à vista ou o total parcelado (quando, raramente, o
parcelado sai mais barato, a mensagem marca "✅ parcelado sai mais barato").

## Outros produtos

O mesmo robô também acompanha (os eletrodomésticos são 127V):

| Arquivo | Produto | Alvo | Resumo diário |
|---|---|---|---|
| `config-glamy.json` | balcão Madesa Glamy 150 cm com tampo | R$ 600 | sim |
| `config-multiprocessador.json` | multiprocessador Mondial Turbo Chef 9 em 1 (MPN-01-BF) | R$ 250 | não |
| `config-panela-pe38.json` | panela de pressão elétrica Mondial Master Cooker 5L (PE-38) | R$ 299 | não |
| `config-panela-pcc20.json` | panela de pressão elétrica Electrolux 6L (PCC20) | R$ 399 | não |
| `config-azzaro-wanted.json` | perfume Azzaro Wanted EDT 100 ml | mínima histórica | não |

Cada produto tem o seu arquivo e o seu próprio histórico em `estado/`. O workflow roda `config.json` e todos
os `config-*.json`, então para acompanhar mais um produto basta copiar um desses arquivos e ajustar. Na
primeira verificação de um produto novo chega uma mensagem "✅ Comecei a acompanhar" com os preços atuais;
depois disso, os que estão sem resumo diário só mandam mensagem quando o preço chega no alvo ou cai de repente.

Campos extras que um produto pode usar:

| Campo | O que faz |
|---|---|
| `exigir_tambem` | termos que também precisam estar no nome (ex.: `"com tampo"`, para ignorar a versão sem tampo) |
| `desconto_pix` (em uma fonte) | desconto fixo no PIX que a loja não mostra nos dados (ex.: `12` na Madesa) |
| `alvo_minima_historica` | avisa quando o menor preço bater a mínima histórica do produto (vem de uma fonte `promobit_produto`) |
| `mostrar_cupons` | nas mensagens, lista os cupons ativos (Promobit) da loja da melhor oferta e estima o preço com o cupom quando ele parece valer para o site todo; sempre "confira no carrinho" |
| `cupons_promobit` (em uma fonte) | página de cupons da loja no Promobit, quando o nome não for reconhecido (ex.: `"epoca-cosmeticos"`) |
| `"tipo": "promobit_produto"` (em uma fonte) | página do produto no Promobit: traz o menor e o maior preço já postados e usa o post mais recente como preço atual se tiver até `max_horas` (padrão 24) |

Nas lojas VTEX (Samsung, Fast Shop, Época, drogarias), cada tamanho/voltagem (SKU) vira uma oferta separada, com
o nome do SKU no título, para o filtro não misturar 50 ml com 100 ml ou 127V com 220V. O Mercado Livre pede
login para robôs; as ofertas de lá chegam pelos posts do Promobit.

## Caçador de preço bugado (`cacador.py`)

Um segundo robô, no mesmo workflow (job `cacador`), que não acompanha um produto específico: ele lê as
promoções novas de toda a internet e avisa no Telegram quando alguma tem cara de erro de preço.

1. **Fontes** (configuradas em `cacador.json`):
   - **Promobit**, pela API pública que o próprio site usa;
   - **Gatry**, pela página de promoções;
   - **Canal oficial do Pelando no Telegram** (`t.me/s/pelandobr`, a prévia pública, sem login). O site do
     Pelando bloqueia robôs vindos do GitHub, por isso o canal. Dá para incluir outros canais públicos em
     `fontes.telegram.canais` (só o nome do canal).
2. **Filtro barato**, sem custo: vira candidata a oferta com palavra de bug no título ou no texto ("bug",
   "bugado", "erro de preço"...), com desconto de `desconto_minimo_pct`% ou mais (e preço antigo de pelo menos
   `preco_antigo_minimo`), ou muito curtida no Promobit com desconto alto. Ofertas com mais de
   `idade_maxima_horas` são ignoradas, e a mesma promoção em sites diferentes é analisada uma vez só.
3. **Opinião do Gemini**: cada candidata vai para o Gemini, que pesquisa no Google o preço normal e a reputação
   da loja e devolve veredito, nota de 0 a 10 e a chance de a loja honrar (pelo CDC a loja cumpre a oferta, mas
   pode cancelar quando o erro é grosseiro). Só chega no Telegram o que for "bug provável" ou "promoção muito
   boa" com nota `nota_minima` ou mais. No máximo `max_analises_por_rodada` análises por rodada.
4. **Sem a chave do Gemini** (ou se ela falhar), o caçador avisa só os candidatos mais fortes, marcados como
   "sem análise da IA".

### Ligar a IA

1. Em <https://aistudio.google.com/app/apikey>, crie (ou copie) uma chave da API do Gemini.
2. No repositório: **Settings → Secrets and variables → Actions → New repository secret**, nome
   `GEMINI_API_KEY`. Não cole a chave em nenhum arquivo do repositório.

Na primeira rodada chega "✅ Caçador de preço bugado ligado", dizendo quantas ofertas ele leu de cada fonte e
se a IA está funcionando. Para testar na hora: **Actions → Caçador de preço bugado → Run workflow** com
`teste`. Os modelos tentados ficam em `gemini.modelos`, em ordem; o primeiro que existir para a sua chave é usado.

O caçador tem o próprio workflow (`cacador.yml`) e roda a cada 10 minutos, 24 horas por dia.

### Custo da IA

O que mais pesa na conta do Gemini é o "raciocínio" (tokens que o modelo gera pensando antes de responder).

- `gemini.raciocinio`: nível de raciocínio no dia a dia. `null` usa o padrão do modelo (melhor análise);
  `"low"` sai uns 70% mais barato, com o mesmo veredito nos testes, mas o "preço normal" fica menos preciso.
- `gemini.raciocinio_bug`: o mesmo, só para candidatos com palavra de bug ("bug", "erro de preço"...).
- `gemini.max_analises_por_dia`: teto diário (60 ≈ R$ 2,40 por dia no padrão). Passou dele, o que não tem
  palavra de bug fica de fora (nada chega ao grupo sem análise) e você recebe um aviso no privado. Candidatos
  com palavra de bug sempre são analisados.

O log de cada rodada mostra os tokens de cada análise e o total do dia ("IA hoje: ...").

### Consistência das notas

O modelo pode julgar a mesma oferta de jeitos diferentes conforme o que a pesquisa encontra (ex.: uma cama box
"70% off" no Mercado Livre levou de 2 a 7 na mesma tarde, porque às vezes a pesquisa achava o frete de R$ 1.000).
Para isso não chegar ao grupo:

- `ler_comentarios`: lê a página do post no Promobit e manda para a IA quem vende e os comentários dos usuários
  ("frete mais caro que a cama"). É grátis.
- Critérios fixos no prompt: custo total (frete, cupom, variação) e evidência concreta para chamar de bug.
- `gemini.segunda_opiniao_bug`: todo "bug provável" com nota de aviso passa por uma contraprova, uma segunda
  análise que procura explicações que não sejam erro. Só vai como bug se as duas concordarem. Bug é raro, então
  o custo extra é pequeno.
- `nota_minima_bug`: régua própria para bug (4). A IA dá nota baixa a bug absurdo porque a loja tende a
  cancelar, mas pedir não custa nada; a mensagem mostra a chance de a loja honrar. Promoção segue `nota_minima`.

### Mandar as ofertas para um grupo do Telegram

As ofertas do caçador podem ir para um grupo; os avisos técnicos (IA fora do ar, fontes falhando) continuam
chegando só no seu chat com o bot.

1. No Telegram, crie o grupo, adicione o bot e quem mais quiser, e mande `/start` lá dentro.
2. Em até 24 horas: **Actions → Caçador de preço bugado → Run workflow** com `grupo`. O bot manda o ID
   dentro do próprio grupo (o número não aparece no log, que é público).
3. Crie o secret `TELEGRAM_CHAT_ID_CACADOR` com esse número, com o sinal de menos.
4. Rode `teste` para ver uma oferta chegar no grupo. Para voltar ao chat privado, é só apagar o secret.

### Radar de preços nas lojas (`radar.py`)

O caçador lê sites de promoção; o radar lê **direto o catálogo das lojas**, para pegar o erro antes de virar
post. Começou com perfumes em cinco lojas VTEX (Época, Drogaria São Paulo, Drogarias Pacheco, Extrafarma e
Pague Menos): cerca de 13 mil itens com estoque, lidos em uns 30 segundos.

- Roda dentro do workflow do caçador, no máximo a cada `intervalo_minutos` (30), e guarda o **histórico de
  preço de cada item** (menor preço com estoque por dia, 30 dias) no cache do GitHub, um mini-Keepa.
- Vira candidato quando, no mesmo item (mesmo código de barras):
  - o preço cai `queda_minima_pct` (40%) abaixo do normal da própria loja, bate a mínima dela e fica mais
    barato que as outras lojas (queda de campanha em todo mundo não conta);
  - fica `abaixo_outras_lojas_pct` (40%) abaixo das outras empresas, desde que tenha caído na própria loja;
  - fica `desconto_declarado_pct` (80%) abaixo do preço "de" da própria loja.
- Lojas da mesma empresa (`grupo`: Drogaria SP + Pacheco, Pague Menos + Extrafarma) não servem de comparação
  entre si, e o mesmo item caído nas duas vira um candidato só.
- O candidato vai para a mesma IA do caçador, com o histórico e os preços das outras lojas na pergunta (com
  contraprova se parecer bug). Só vai para o grupo com a mesma nota mínima; a mensagem traz "📡 Radar".
- Limites próprios: `max_analises_por_rodada` (2) e `max_analises_por_dia` (10). O mesmo item só é analisado
  de novo se cair mais 10% ou depois de `nao_repetir_dias` (3).
- A primeira leitura só monta o histórico (o que já estiver barato nela fica marcado como visto) e manda
  "📡 Radar de preços ligado" só para você. Loja que falhar 3 leituras seguidas gera um aviso só para você.
- No `teste` do caçador, o radar também lê na hora e manda só para você a análise da maior queda do momento.

Para incluir outra loja VTEX, acrescente em `lojas` o endereço e o código da categoria (aparece em
`categoriesIds` na API `/api/catalog_system/pub/products/search?ft=nome do produto`).

## Disparo (cron-job.org)

O agendamento do próprio GitHub atrasa e pula muitos horários (às vezes roda uma vez a cada várias horas),
então quem dispara os dois workflows é o [cron-job.org](https://cron-job.org), que é gratuito. Ele chama a API
do GitHub com um token que só tem permissão para disparar o Actions deste repositório.

### 1. Token do GitHub (só para disparar)
**Settings** (do seu perfil) → **Developer settings** → **Personal access tokens** → **Fine-grained tokens** →
**Generate new token**:
- *Repository access*: **Only select repositories** → `alerta-wd13fg`
- *Permissions → Repository permissions → Actions*: **Read and write** (nada mais)
- *Expiration*: até 1 ano. Quando vencer, o cron-job.org começa a falhar (e avisa por e-mail); é só gerar outro.

O token aparece uma vez só: copie direto para o cron-job.org e não guarde em nenhum arquivo do repositório.

### 2. Dois cronjobs no cron-job.org
Em **Create cronjob**, para cada linha da tabela:

| Título | URL | Frequência |
|---|---|---|
| Caçador de preço bugado | `https://api.github.com/repos/joaovrmdev/alerta-wd13fg/actions/workflows/cacador.yml/dispatches` | a cada 10 minutos |
| Alertas de preço | `https://api.github.com/repos/joaovrmdev/alerta-wd13fg/actions/workflows/alerta.yml/dispatches` | a cada 30 minutos |

Na aba **Advanced** de cada um:
- *Request method*: **POST**
- *Headers*:
  - `Accept`: `application/vnd.github+json`
  - `Authorization`: `Bearer <o token>`
  - `X-GitHub-Api-Version`: `2022-11-28`
  - `Content-Type`: `application/json`
- *Request body*: `{"ref":"main","inputs":{"modo":"verificar"}}`

Use **Test run**: a resposta certa é `204` (ou `200`), e em seguida aparece uma execução nova na aba Actions.
Se vier `401`/`403`, o token está errado ou sem a permissão de Actions; `404`, a URL ou o nome do workflow.

Intervalos menores que esses funcionam, mas os termos do GitHub Actions pedem uso ligado ao projeto e sem
sobrecarga, e as lojas também bloqueiam quem consulta demais.

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
- O GitHub pausa agendamentos de repositórios públicos sem nenhuma atividade por 60 dias (isso só afeta o
  agendamento reserva; o disparo pelo cron-job.org continua). Se acontecer, é só reativar na aba Actions.
