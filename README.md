# ViralPost Studio

Aplicação Flask que transforma uma ideia em um roteiro de hooks e scripts e em um carrossel visual pronto para publicar — usando um endpoint LLM OpenAI-compatible, fotos do Pinterest ou do Instagram (busca **sem token**) ou do Unsplash, e renderização estilo **TikTok photo post** (1080×1350, 4:5). Painéis antigos do goviral.ai continuam podendo ser importados, mas não são necessários.

> **Status:** MVP v0.22 — sem repetição entre gerações + 5 alternativas por imagem
> **Stack:** Python 3.11 · Flask 3 · Jinja2 · WTForms · Pillow · Docker
> **Idioma inicial:** Português (pt-BR)

---

## 🎯 O que mudou na v0.22

- 🐛 **A cota de comida vetava a foto que só tinha um café na mesa do fundo** — o filtro olhava *menção*, não *foco*: qualquer `coffee`/`café` no alt zerava a foto para cenário. Num tema como `rotina matinal` isso é quase todo o acervo — medido no mesmo conjunto de 12 fotos, sobravam **3 candidatas de cenário**, e o carrossel repetia foto. Duas causas somadas. A primeira é o que a cota quer dizer: ela limita o que a foto **mostra**, não o que dá para ver nela, então agora vale o **primeiro assunto citado e em primeiro plano** — "a man drinking a coffee" é foto de pessoa, "a bright bedroom **with** a cup of coffee" segue sendo foto de quarto, e "a cup of coffee on a wooden table" continua sendo comida. A segunda é que **o `title` cai na query da busca quando o provider não manda legenda**, e a query traz as palavras do próprio pool (`… food smoothie fruit breakfast`): o casting lia os termos da busca como se fossem a legenda da foto, e com um `café` no tema digitado o acervo de cenário caía para **2 de 12**. O texto que o provider escreveu sobre a foto agora tem campo próprio (`PinterestImage.alt`) e é o único que o casting lê — o `title` continua servindo à prévia. No mesmo acervo: **3 → 6 candidatas de cenário**, e as três que voltaram são as certas (o quarto com a xícara ao fundo, a cozinha que a busca de comida trouxe por engano, a paisagem que a busca de retrato trouxe por engano). De quebra o mesmo corte vale para o hook, que rejeitava "a woman holding a cup of coffee" por causa da xícara.
- 🐛 **A mesma hashtag devolvia o mesmo carrossel** — o "ponto de corte sorteado" da v0.7 tinha virado enfeite. O piso de resolução estrito da v0.21 deixava o pool tão curto que não havia o que sortear: medido em 2026-08-22 na query `morning routine aesthetic`, **11 dos 40** pins cobriam 1080×1350, então uma janela de 10 tinha três posições possíveis e duas gerações repetiam **9,4 de 10** fotos. Três correções somadas: o pool subiu para **120 pins** (a biblioteca já paginava sozinha — o custo real foi 3,0s → 4,8s, não a segunda requisição que o comentário antigo temia), a janela contígua virou **amostra aleatória** do pool inteiro, e as fotos que já saíram vão para o fim do sorteio. Medido ponta a ponta, duas gerações seguidas com o mesmo tema: **0 de 6** fotos repetidas.
- ✅ **A cota limita o que é escolhido, não o que pode ser escolhido** — a galeria de cada slide era o pool da categoria dele, então um slide de cenário cuja categoria voltasse curta ficava com uma alternativa só e a troca com um clique não existia na prática. Agora toda imagem do carrossel oferece **no mínimo 5 alternativas além da que ela já recebeu** (galeria de 6, `MIN_IMAGE_ALTERNATIVES`): primeiro as da própria categoria, depois as melhores do resto do acervo. Vale também para o slide de fecho, cuja galeria de prints do GoViral subiu de 5 para 6 pelo mesmo motivo. A **escolha** continua obedecendo às cotas de pessoa, comida e à cota paga do Instagram — o que mudou é o que a prévia deixa você escolher por cima dela.
- ✅ **Os pools de busca cobrem a galeria, não só o carrossel** — buscar 6 fotos de retrato para gastar 1 no hook deixava a prévia sem material. Cada pool agora pede a cota **mais** as alternativas, com piso de 14 por categoria. Numa geração de 6 slides (2 pessoas, 1 comida), a galeria saiu de ~16 para **48** fotos.
- ✅ **O piso de resolução mede ampliação, não largura bruta** — exigir 1080×1350 literais reprovava o formato mais comum do acervo por causa de 56px: `1024×1536` é o tamanho nº 1 do Pinterest e cobre o slide com **1,055×** de ampliação, que não se vê. O piso agora é o fator de `cover` (`_MAX_UPSCALE = 1,10`), e o pool usável saltou de **40 para 71** dos mesmos 120 pins. Acima da tolerância a foto continua recusada — o ponto do piso nunca foi a medida, foi não deixar origem pequena virar PNG borrado.
- 🐛 **A busca não achava nada e o mock fingia que sim** — no log de produção, `query='lifestyle cozy #aesthetic #praia #vibe bellebres girly aesthetic lifestyle travel interior workspace'` devolvia **0 imagens**. Três defeitos somados: o `#` e o `@perfil` iam crus para um banco de imagens que não conhece nenhum dos dois; termos repetidos (`lifestyle` e `aesthetic` chegavam duas vezes, porque o tema e as dicas de casting se sobrepõem) gastavam vagas; e nada tentava uma busca mais curta. Pior, **0 resultado cai no mock — e o mock é determinístico por query** (`hash(query)` escolhe a paleta), então a mesma hashtag passava a devolver os mesmos gradientes para sempre: o "cache forçado" que se via na tela. Agora a query é normalizada e reduzida em três degraus até achar algo, e quando nem assim acha, a prévia diz o motivo em vez de entregar gradiente mudo.
- 🐛 **A reentrada de página do Unsplash repetia a mesma página** — `((page - 1) % total_pages) + 1` devolve `page` sempre que `total_pages >= page`, então a segunda chamada era idêntica à primeira e gastava cota à toa. Agora a reentrada vai para a página 1, que é a que sempre tem resultado.
- ✅ **A memória de fotos vale para o Unsplash também** — ela só chegava ao `pinterest_scrape`, e o Unsplash é quem está ligado em produção. Ele agora pede o dobro de fotos do que o carrossel usa e deixa por último o que já saiu.

- ✅ **Memória do que já saiu** — `instance/recent_media.json` guarda as fotos que **entraram nos slides** (não as alternativas: marcar as ~30 candidatas de cada geração esgotaria a memória em duas rodadas). É preferência, não veto — acervo pequeno continua devolvendo carrossel, só na ordem inversa. A identidade é a URL normalizada, não o `image_id`: o mesmo pin muda de id entre buscas.

### A mesma hashtag não devolve o mesmo carrossel

Três camadas, e nenhuma delas sozinha resolvia:

| Camada | O que faz | Por que não bastava sozinha |
| --- | --- | --- |
| **Pool de 120** | Triplica o acervo bruto por query. | Sem sorteio, um pool maior devolve os mesmos primeiros N. |
| **Piso por ampliação** | Aproveita 71 dos 120 pins em vez de 40. | Um pool grande e um piso que reprova 2/3 dele dá no mesmo pool curto. |
| **Amostra aleatória** | Sorteia quais pins entram, em vez de deslizar uma janela contígua. | Sorteio sem memória ainda repete por acaso: ~2,8 de 10. |
| **Query que acha algo** | Normaliza e encurta até a busca devolver fotos. | Query que não acha nada cai no mock, e o mock é determinístico por query — a repetição fica **perfeita**. |
| **`recent_media.json`** | Manda para o fim do sorteio o que já saiu nos slides anteriores. | Sem pool fundo, a memória satura em uma rodada e vira sorteio puro. |

O arquivo fica no `instance/` (que está no `.gitignore`), como a pessoa fixada — os projetos vivem em memória com TTL e a memória precisa sobreviver ao restart. Apagá-lo zera o histórico e não quebra nada.

Medido ponta a ponta com a query do log de produção (hashtags, `@perfil` e 12 termos), três gerações seguidas de 6 slides: **18 fotos distintas em 18 slots**, zero gradiente mock, e no mínimo 5 alternativas por imagem.

---

## 🎯 O que mudou na v0.21

- ✅ **Quantidade de pessoas/modelos e comida por carrossel** — os formulários `/goviral` e `/create` ganharam **"Fotos com pessoas/modelos"** (1 a 12, incluindo o hook) e **"Fotos de comida"** (0 a 12). A soma é limitada ao número real de slides; o restante fica para cenário geral. Não há variável nova no Render: a escolha é feita em cada geração, como a cota do Instagram.
- ✅ **Três buscas para reduzir repetição** — pessoa, comida e cenário usam pools e queries separados. O pool de comida inclui refeições, smoothie, frutas e bebidas; imagens repetidas entre pools são deduplicadas e o casting intercala as categorias, usando cada foto uma vez antes de repetir. O Qwen-VL configurado agora distingue `food` de `scene`; seu veredicto vence metadados e o pool de origem.
- ✅ **Alta resolução virou requisito, não preferência** — Pinterest e Instagram só aceitam origens que cubram `SLIDE_WIDTH`×`SLIDE_HEIGHT` (1080×1350 por padrão). O piso não cai mais quando o acervo é fraco; a fonte devolve menos fotos ou fallback com aviso em vez de ampliar arquivo pequeno. No Unsplash, o CDN recebe `w=1080`, `h=1350`, `fit=crop` e `q=85` para entregar a imagem final no tamanho do slide.

---

## 🎯 O que mudou na v0.20

- ✅ **Quantidade de fotos do Instagram escolhida por geração** — os formulários `/goviral` e `/create` ganharam o campo **"Fotos do Instagram no modo combinado"** (1 a 12, com 1 como padrão recomendado). Em `instagram_pinterest`, uma foto do Instagram é reservada para o pool do hook, o restante da cota vai para o pool de cenário e o Pinterest preenche os outros slides pelos termos da busca. A cota é limitada automaticamente ao tamanho real do carrossel.
- ✅ **`@perfil` fica só no Instagram** — antes as duas fontes recebiam a mesma string; buscar `@usuario` fazia o Pinterest procurar também pelo handle, enquanto as duas buscas de casting chamavam o mesmo perfil do Instagram. Agora o Instagram conserva `@perfil`, o Pinterest recebe apenas tema/palavras-chave e uma `#hashtag` vira uma palavra normal na busca complementar. Assim o hook pode vir do perfil e o b-roll continua guiado pelos termos visuais.
- ✅ **Apify com custo e payload proporcionais à escolha** — quando a cota do modo combinado está ativa, `resultsLimit`, `maxItems` e o `limit` do dataset recebem exatamente a quantidade escolhida; `clean=1` remove campos ocultos/vazios. O dataset do mesmo `@perfil`/hashtag também é reutilizado entre os pools de hook e cenário, evitando um segundo run idêntico. O conversor aceita `childPosts`, `originalWidth/Height`, `pk` e variações de owner do schema atual, mantendo uma capa por post para não transformar carrossel do Instagram em fotos repetidas.

---

## 🎯 O que mudou na v0.19

- ✅ **Geração automática sem copiar e colar do goviral.ai** — a tela `/goviral` recebe uma ideia, público, idioma e número de imagens e pede ao LLM um painel completo com `Hook`, `Script N`, `Position N` e dois parágrafos por script. O resultado volta para a caixa editável e segue pelo parser, busca de imagens, prévia e exportação já existentes.
- ✅ **Saída validada antes de chegar às imagens** — a resposta precisa ter exatamente o número de scripts pedido e duas caixas não vazias por script. JSON parcial, posição errada ou conteúdo vazio são descartados; o endpoint tenta uma vez sem `response_format` e `reasoning_effort` para compatibilidade com providers OpenAI-compatible que não aceitam esses campos.
- ✅ **Regras do Creator Program incorporadas ao prompt** — 5-6 imagens como padrão, narrativa concreta, fatos preservados, sem autoridade ou métricas inventadas, capitalização consistente, caixas curtas, sem travessão longo e menção natural ao Go Viral app quando habilitada. O gerador também devolve tema e palavras-chave visuais para a busca de fotos.
- ✅ **Importação manual continua como fallback** — a caixa do roteiro aceita um painel antigo do goviral.ai e a rota `/goviral/parse` permanece disponível para conferir a distribuição antes de gerar.

---

## 🎯 O que mudou na v0.18

- 🐛 **As fotos do Instagram saíam brancas na prévia — e o defeito nunca foi da busca** — buscar `@perfil` (ou hashtag) via Apify devolvia os posts certos, com metadado certo (o alt "Photo by BELLE…" e a fonte na legenda), e ainda assim a galeria e o fundo do slide mostravam quadrados brancos. Medido em 2026-08-16: o CDN do Instagram (tanto `scontent-*.cdninstagram.com` quanto `instagram.f*.fna.fbcdn.net`, o host que o caminho de perfil costuma devolver) responde `200` com a foto **e** o header `Cross-Origin-Resource-Policy: same-origin`. O navegador baixa a imagem e a **descarta** na checagem de CORP, porque a página é de outra origem — hotlink de foto do Instagram não renderiza em navegador moderno, com a URL viva e o download do servidor funcionando. É por isso que o sintoma engana: o PNG exportado sai com a foto (render é do servidor) e a prévia não. Nenhum atributo de `<img>` (`referrerpolicy`, `crossorigin`) contorna CORP.
- ✅ **`/image-proxy` — a prévia pede a foto ao app** — o filtro `browser_src` dos templates troca as URLs do CDN do Instagram por `/image-proxy?u=…` na galeria, no fundo do slide e no `data-image-url` que o JS usa ao trocar de foto; o app baixa do lado do servidor, onde CORP não vale, e devolve com `Cache-Control` para o navegador guardar o thumb. Pinterest, Unsplash e o mock passam intactos — os CDNs deles não mandam o header. **Só hosts do CDN do Instagram passam pelo proxy** (lista fechada; qualquer outro host responde 404, sem chamada de rede): sem isso o endpoint seria um SSRF de brinde. URL assinada que expirou vira 502 — o thumb quebra quando a foto está morta de verdade, que é o contrato documentado das URLs do `scontent` (servem à sessão, não para guardar).

---

## 🎯 O que mudou na v0.17

- ✅ **Unsplash + Pinterest como fonte combinada** — `IMAGE_PROVIDER=unsplash_pinterest`, ou a opção nova **"Unsplash + Pinterest (metade de cada)"** no seletor "Fonte das fotos" dos dois formulários. A mecânica é a mesma do `instagram_pinterest`: cada fonte busca com o mesmo limite, o resultado sai **intercalado** (um de cada) até fechar o carrossel, uma fonte preenche o que a outra não trouxe e o resultado mock de uma fonte que caiu fica de fora. É o combinado para quem tem a chave (gratuita) do Unsplash e quer juntar o acervo dele com a estética do Pinterest — sem tocar no Instagram e portanto sem `APIFY_TOKEN`. A metade Pinterest continua sendo scraping: as [ressalvas de compliance](#️-limitações-e-compliance) valem inteiras e o modo nunca entra sozinho no `auto`.
- ✅ **Unsplash sem chave falha rápido e nomeia o que falta** — no modo combinado o cliente Unsplash existe mesmo sem `UNSPLASH_ACCESS_KEY` (o par entra inteiro, como o Instagram sem token no outro combinado). Em vez de gastar um round-trip fadado ao 401 — cujo motivo diria "chave recusada", de uma chave que **não existe** —, a busca cai no mock localmente com "sem UNSPLASH_ACCESS_KEY configurada". Como nos outros combinados, o motivo só aparece na prévia quando as DUAS fontes falham; com o Pinterest respondendo, ele preenche e o carrossel sai com fotos.

---

## 🎯 O que mudou na v0.16

- 🐛 **A busca por hashtag via Apify voltava 1 item e nenhuma foto utilizável** — com tudo configurado certo (`APIFY_TOKEN`, `IMAGE_PROVIDER=instagram_pinterest`), o carrossel caía no gradiente mock com o aviso "A Apify devolveu 1 itens, mas nenhuma foto utilizável". O dataset do run conta o que houve (medido em 2026-08-16): a fase de busca do actor (`search` + `searchType=hashtag`) virou uma consulta ao **Google** (`site:instagram.com/explore/tags/* "aesthetic"`), que casou a hashtag **errada** (#gaesthetic) e devolveu a *entidade do resultado da busca* (`searchTerm`/`postsCount`/`url`) como único item — sem raspar post nenhum ("Crawled 0/1 pages" no log do run). Não era nome de campo trocado, como o aviso hipotetizava: era um dataset sem nenhum post dentro.
- ✅ **A hashtag agora vai como URL direta, igual ao `@perfil`** — `directUrls: ["https://www.instagram.com/explore/tags/<tag>/"]` pula a fase de busca do actor e devolve os posts no formato que o conversor já esperava (`displayUrl`, `dimensionsWidth/Height`, `alt`, `type`), verificado num run real: 5 posts em 5 itens. O resto do caminho não muda — piso de resolução, casting por metadado e os freios de fatura (`maxItems`, `timeout` do run) seguem os mesmos.

---

## 🎯 O que mudou na v0.15

- 🗑️ **A API oficial v5 do Pinterest foi removida — ela nunca chegou a buscar nada** — `PINTEREST_ACCESS_TOKEN`, `PINTEREST_API_BASE_URL`, o `PinterestV5Client` inteiro (busca + `validate_token`) e o provider `pinterest_v5` saíram. O motivo é o mesmo que criou o `pinterest_scrape` na v0.7: o `/search/pins/` da v5 exige **Standard Access**, aprovação manual da Pinterest que este projeto nunca teve — então o primeiro degrau da escada do `auto` era código que só sabia devolver `403`. Manter os dois caminhos custava um cliente inteiro para manter, uma variável que parecia obrigatória no `.env` e no `render.yaml`, e um diagnóstico a mais no `/health` sugerindo que faltava configurar um token. A `pinterest-dl` faz a mesma busca sem credencial nenhuma.
- ✅ **A escada do `auto` encurtou para `UNSPLASH_ACCESS_KEY` → mock** — e continua **sem escolher scraping sozinho**, que era e segue sendo uma decisão de quem publica (ver [compliance](#️-limitações-e-compliance)). Para fotos do Pinterest, `IMAGE_PROVIDER=pinterest_scrape` — a escolha explícita de sempre.
- ✅ **Um token esquecido no ambiente não muda mais nada** — quem tinha `PINTEREST_ACCESS_TOKEN` definido no Render pode apagá-lo, mas deixar não quebra nem desvia a escada: a variável simplesmente não é lida. Há teste travando exatamente isso, porque "sobrou no painel e mudou o comportamento" é o tipo de coisa que só aparece em produção.

---

## 🎯 O que mudou na v0.14

- 🐛 **O muro do Instagram não é gate de IP — e trocar de proxy nunca ia resolver** — a v0.13 diagnosticou o `302 → /accounts/login/` como IP no balde ("IPs de datacenter caem quase sempre") e o aviso da prévia mandava *"troque o proxy por um de IP residencial/móvel"*. O diagnóstico estava errado, e o custo dele foi real: quem seguiu o conselho contratou proxy residencial (ScrapeOps, `INSTAGRAM_PROXY_INSECURE=true`, tudo certo) e continuou caindo no gradiente mock em toda geração. Medido em 2026-08-16, o `/api/v1/tags/web_info/` responde o **mesmo 302** em três saídas independentes — datacenter (Render), IP residencial doméstico e os exits residenciais do ScrapeOps —, com e sem bootstrap de cookie (`csrftoken` da home), e o `i.instagram.com` também. O gate é do **endpoint**, não do IP: o Instagram fechou a busca anônima por hashtag. Não há proxy que passe por isso, e o `/explore/tags/<tag>/` também não traz mais os posts embutidos no HTML (`display_url`/`scontent` sumiram das 601 KB de página) — não sobrou caminho anônimo. O aviso da prévia agora diz isso e aponta a saída que funciona, em vez de mandar caçar proxy melhor.
- ✅ **`APIFY_TOKEN` — a Apify como fonte do Instagram, e a única com chance na hashtag** — os outros transportes eram todos a mesma ideia ("saia por outro IP"), e é justamente a ideia que o muro derruba. A Apify é diferente em espécie: em vez de repassar a nossa chamada, ela roda um **actor** que raspa com sessão própria e devolve o **dataset dele**. Por isso não é um transporte a mais no `_get_json` e sim um caminho próprio: `POST /v2/acts/<actor>/run-sync-get-dataset-items` roda e devolve os itens na mesma resposta (sem polling do run nem segunda chamada ao dataset, que seriam três round-trips dentro do `POST /generate`), e `_ig_entry_from_apify` converte o item **na fronteira** — daí para baixo o piso de resolução, o casting por metadado (o `alt` do actor é o mesmo *accessibility caption*), o `_cut_pool` e o `_to_image` seguem valendo sem saber de onde a foto veio. Cobre os dois caminhos que já existiam: hashtag (`search` + `searchType`) e `@perfil` (`directUrls`, mais previsível que mandar o actor buscar um perfil que já sabemos qual é). Vídeo/reel fica de fora e o carrossel entra pela capa, as mesmas regras do parser v1. Com `SCRAPEDO_TOKEN` e `APIFY_TOKEN` definidos, **a Apify vence** — o outro só troca o IP. `APIFY_ACTOR` permite trocar de actor (o preço por resultado varia); erro do gateway não vira "Instagram bloqueou" (401/402/404/408/429 têm cada um seu motivo na prévia), e dataset cheio sem nenhuma foto aproveitável diz **que os nomes de campo do actor não são os esperados**, que é a hipótese cara de descobrir sozinho.
- ✅ **Dois freios, porque o actor é pago e roda dentro do `POST /generate`** — o pool pedido é `max(nº de fotos × 3, 12)`, não os 40 que o Pinterest traz de graça: sobra folga para o piso de resolução descartar sem multiplicar a conta. O mesmo número vai em `maxItems`, que é o teto de itens **faturados** (para um actor que ignore o `resultsLimit` não virar surpresa na fatura), e o run leva um `timeout` próprio — sem ele o actor herda o timeout da configuração *dele*, a resposta chegaria depois de o gunicorn já ter matado o worker, e worker morto não faz fallback. O timeout do cliente sobe para 90s por causa do cold start, ainda abaixo do `--timeout 180`.
- 🗑️ **`INSTAGRAM_PROXY` e `INSTAGRAM_PROXY_INSECURE` foram removidos** — eram a materialização do diagnóstico errado. Com eles saiu também o retry de 3 tentativas (sem proxy o IP de saída é sempre o mesmo, então repetir é só latência) e o `verify=False`, que era exigência das portas-proxy de agregadores. Quem tinha as variáveis no ambiente pode apagá-las: elas não são mais lidas.
- ✅ **Todas as fontes continuam escolhíveis, e `instagram_pinterest` é a saída sem custo** — o seletor "Fonte das fotos" não mudou: Padrão do servidor, Só Unsplash, Só Pinterest, Só Instagram e Instagram + Pinterest seguem lá. Apify e Scrape.do são **transportes dentro** do Instagram, não fontes novas — então o modo combinado se beneficia da Apify sem nenhuma opção a mais na UI. E o combinado já descarta o resultado mock da fonte que caiu e preenche com a outra: sem token pago nenhum, o carrossel sai **com fotos do Pinterest** em vez de gradiente.

> ⚠️ **Corrigido na v0.16:** o caminho da hashtag por `search` + `searchType` deixou de entregar posts — a fase de busca do actor passou a consultar o Google (casando hashtags erradas) e a devolver a entidade do resultado como único item do dataset. A hashtag agora vai por `directUrls` (`/explore/tags/<tag>/`), como o `@perfil` sempre foi. Ver [v0.16](#-o-que-mudou-na-v016).

---

## 🎯 O que mudou na v0.13

- ✅ **`INSTAGRAM_PROXY` — um IP de saída só para o Instagram** — em produção (Render, AWS…) a busca sem token caía SEMPRE no mock: o Instagram mantém IPs de datacenter no balde do muro de login, então o `GET /api/v1/tags/web_info/` voltava `302 → /accounts/login/` antes de qualquer dado. É gate de rede (o Instaloader documenta o mesmo para IPs compartilhados) e nenhum header resolve — o que resolve é sair por outro IP. O README já apontava o `HTTPS_PROXY`, mas ele é global: mandaria TAMBÉM Groq, Unsplash, ModelScope e Pinterest pelo proxy. A variável nova vale só para as chamadas do Instagram; os downloads do CDN (`scontent…`) continuam diretos, porque as URLs assinadas não são presas ao IP. Em branco, nada muda (`HTTPS_PROXY` continua respeitado, se existir). Portas-proxy de agregadores (ex.: ScrapeOps, `residential-proxy.scrapeops.io:8181` com `mobile=true` no username) interceptam o TLS por design e pedem `INSTAGRAM_PROXY_INSECURE=true` junto — sem isso a chamada morre em SSLError antes de chegar ao Instagram. Como esses pools sorteiam outro IP de saída a cada conexão, o muro de login com proxy configurado é tentado **até 3 vezes** antes do fallback — um exit queimado não condena os próximos (sem proxy não há retry: o IP é sempre o mesmo). Confira em `/health` → `images_diagnostic.instagram_proxy_set`.
- ✅ **`SCRAPEDO_TOKEN` — a mesma busca, saindo pela infra do Scrape.do** — quem não tem um proxy residencial próprio pode apontar um token do [Scrape.do](https://scrape.do): as MESMAS chamadas (`/api/v1/tags/web_info/` e `/api/v1/users/web_profile_info/`) passam a sair pelo gateway deles com `super=true` (proxies residenciais/móveis, 10x créditos por chamada), `extraHeaders` (o `x-ig-app-id` vai num header `sd-*` por cima do fingerprint deles — `customHeaders` substituiria os headers todos e estragaria o disfarce) e `disableRedirection` (o muro de login volta como header e falha rápido, sem baixar o HTML). O parse, o piso de resolução, o casting e os fallbacks não mudam — é só o transporte, então o modo combinado `instagram_pinterest` também se beneficia. Erro do gateway não vira "Instagram bloqueou": 401 (token/créditos), 429 (concorrência do plano) e 502 (os retries deles falharam — sem consumo de crédito) têm cada um seu motivo na prévia. Com `SCRAPEDO_TOKEN` e `INSTAGRAM_PROXY` definidos, o token vence. O timeout da chamada sobe para pelo menos 60s — o gateway tenta vários IPs por dentro, e os 20s da chamada direta a cancelariam no meio (a mesma lição do `VISION_TIMEOUT_SECONDS`). **Scrapling foi reavaliado e segue de fora**: tudo que ele oferece é disfarce de fingerprint (TLS/canvas/WebRTC) ou rotação de proxies que você fornece — contra um gate por IP, sem proxy ele é o mesmo `requests` (testado contra o Instagram em 2026-08-15: TLS do Chrome, bootstrap de cookies e `i.instagram.com`, tudo no mesmo muro).
- ✅ **O muro de login falha rápido e diz o remédio** — o cliente não segue mais o `302` (era ele que baixava a página de login inteira só para falhar no parse de JSON logo depois): o redirect já É a resposta. O motivo que chega à prévia agora aponta a saída — configurar `INSTAGRAM_PROXY`/`SCRAPEDO_TOKEN` ou rodar de outra rede — e, com proxy configurado e ainda assim no muro, diz que o IP **do proxy** caiu no balde (via Scrape.do, que o IP rotaciona a cada chamada — gerar de novo costuma resolver). Automatizar login continua fora do escopo (a mesma regra do goviral.ai): uma sessão logada atravessaria o muro, mas repassar cookies de conta é exatamente o que este projeto não faz.

> ⚠️ **Corrigido na v0.14:** a premissa dos três itens acima — "o muro é por IP, logo outro IP de saída resolve" — foi **falsificada por medição**. O `302` volta igual de datacenter, de residencial doméstico e dos exits residenciais do ScrapeOps: o gate é do endpoint. `INSTAGRAM_PROXY` e `INSTAGRAM_PROXY_INSECURE` **não existem mais**; `SCRAPEDO_TOKEN` continua, mas só ajuda no `429` do caminho `@perfil`. Para a hashtag, o caminho é `APIFY_TOKEN`. Ver [v0.14](#-o-que-mudou-na-v014).

---

## 🎯 O que mudou na v0.12

- ✅ **As duas caixas do slide saem espalhadas: uma no topo, outra no pé** — o layout "pergunta em cima, resposta embaixo" dos photo posts nativos virou o padrão. Antes as caixas saíam empilhadas no terço superior, praticamente coladas (o respiro entre elas era só 4,5% da altura), e o resto da foto ficava vazio. Agora um slide com 2+ caixas abre a primeira em 12% da altura e fecha a última em 88%, com o miolo distribuído por igual — a mesma conta do `justify-content: space-between`, que é exatamente como a prévia espelha o PNG (o padding vertical dela virou 15% da largura = 12% da altura no 4:5). O hook (uma caixa) continua ancorado embaixo, slides de uma caixa continuam na âncora do papel, e o arraste manual segue mandando: os slots são calculados sobre TODAS as caixas com texto, então arrastar uma não muda o lugar das outras. Texto alto demais para espalhar cai na pilha de sempre, que já sabe encolher a fonte.
- ✅ **"Black outline" igual ao da referência** — o contorno subiu de 8% para **12% do corpo da fonte** (na prévia, 0.24em de `-webkit-text-stroke`, porque o CSS centra o traço na borda) e TODAS as caixas do outline saem no corte **SemiBold** da TikTok Sans: a legenda clássica do TikTok tem um peso só, e o corpo em Medium sob um contorno preto grosso ficava fraco, desigual da headline. A geometria (largura, passo entre linhas, duas passadas) não muda.
- ✅ **Instagram como fonte de fotos, e um seletor de fonte na UI** — `IMAGE_PROVIDER=instagram_scrape` busca no Instagram **sem token**, pelos mesmos endpoints web anônimos que o [instagram-php-scraper](https://github.com/postaddictme/instagram-php-scraper) usa (`/api/v1/users/web_profile_info/` e `/api/v1/tags/web_info/`, com o `x-ig-app-id` do site); `instagram_pinterest` combina Instagram + Pinterest sem token, **intercalados** (um de cada até fechar o limite, e um preenche quando o outro falha — resultado mock de uma fonte que caiu fica de fora). Nos formulários (`/create` e `/goviral`), o novo seletor **"Fonte das fotos"** escolhe por geração — Padrão do servidor, Só Unsplash, Só Pinterest, Só Instagram ou Instagram + Pinterest — vencendo o `IMAGE_PROVIDER` daquela vez. O Instagram não busca texto livre sem login, então a query vira **uma hashtag**: o tema sem espaços/acentos e sem as palavras das queries de casting (`rotina matinal` → `#rotinamatinal`); um `#hashtag` ou `@perfil` digitado no tema/palavras-chave vence a derivação, e `@perfil` busca as fotos do perfil. O piso de resolução, a preferência por retrato e o ponto de corte sorteado são os mesmos do `pinterest_scrape`; o `accessibility_caption` ("May be an image of 1 person…") alimenta o casting por metadado como o alt do Pinterest. **Acesso anônimo é liberado e bloqueado por IP pelo próprio Instagram**: quando o site devolve a página de login (ou 401/429), o carrossel cai no gradiente mock com o motivo escrito na prévia — o mesmo contrato instável, e o mesmo opt-in explícito, do Pinterest sem token (nunca entra no `auto`; ver [compliance](#️-limitações-e-compliance)).

---

## 🎯 O que mudou na v0.11

- ✅ **Fixar a pessoa do hook e repeti-la nos próximos carrosséis (opcional)** — na prévia, a imagem 1 ganhou o botão **"📌 Fixar esta pessoa"**: ele guarda o pin da foto do hook em `instance/pinned_person.json` (sobrevive a restart; os projetos vivem em memória com TTL). Nos formulários (`/create` e `/goviral`), quando existe pessoa fixada aparece um checkbox — **desligado por padrão** — "Buscar mais fotos da pessoa fixada": com ele marcado, o pool de retrato do hook vem dos **pins relacionados** àquele pin (o "mais como este" do Pinterest, via `related()` da `pinterest-dl`) em vez da query de retrato. Para um pin de retrato os relacionados costumam trazer a mesma pessoa — é similaridade visual do próprio Pinterest, **nenhum reconhecimento facial**, e por isso "costuma", não "sempre": a galeria da prévia continua lá para conferir e trocar. O pool de cenário não muda (a pessoa fixada é do hook; o resto segue b-roll), e o recorte é o mesmo da busca por query: piso de resolução, retrato primeiro, ponto sorteado. Só funciona com `IMAGE_PROVIDER=pinterest_scrape` (Unsplash não tem "fotos relacionadas" na API pública); qualquer falha — ninguém fixado, provider sem `related`, pin sem relacionados, erro de rede — cai na busca de retrato de sempre com o motivo nos avisos da prévia. Fixar uma foto que não é pin do Pinterest responde 422 explicando; "Esquecer a pessoa fixada" apaga o arquivo.
- 🐛 **"Salvar edição" e "Baixar ZIP" falhavam com 404 no Docker** — o gunicorn rodava com `--workers 2`, mas os projetos vivem na memória **do processo** (`SessionStore`): o `/generate` criava o carrossel num worker e o POST de salvar/exportar abria conexão nova e caía no outro na metade das vezes — "Projeto não encontrado ou expirado" com o carrossel recém-gerado na tela. O intermitente é a assinatura: requisições em sequência rápida reusam a conexão (keep-alive de 2s do gunicorn) e acertam o worker; depois de alguns minutos editando, a conexão fecha e o próximo POST sorteia. Agora é `--workers 1 --threads 8` — a concorrência vem das threads (o store já tem lock) e multi-worker fica condicionado a store externo (Redis/DB), como "Limitações" sempre documentou.

---

## 🎯 O que mudou na v0.10

- ✅ **Legenda "black outline"** — segundo corte de legenda nativo do TikTok, como estilo `sticker_outline`: texto branco com contorno preto, sem caixa. Mesma geometria do sticker (largura, passo entre linhas, arraste e resize por caixa, prévia em duas camadas) — só a tinta muda. No PNG o contorno é `stroke_width` do Pillow (8% do corpo da fonte, crescendo para fora do glifo), desenhado em duas passadas como as etiquetas: todos os contornos primeiro, todas as letras depois, senão o traço da linha de baixo comeria o rabo dos "g" da linha de cima. Na prévia, a camada de baixo troca a etiqueta branca por `-webkit-text-stroke` (0.16em, porque o CSS centra o traço na borda — metade fica visível) e a de cima pinta a letra branca.
- ✅ **O carrossel fecha mostrando o GoViral app** — a última imagem (o slide de CTA) recebe um print do app, sorteado da pasta `goviral_assets/` na raiz do repo, com mais 4 alternativas na galeria da prévia — a mesma mecânica das fotos de busca: palpite inicial, trocável com um clique. A pasta é o liga/desliga (sem ela, nada muda), os prints entram DEPOIS do casting (senão virariam "cenário" dos outros slides) e nunca no carrossel de 1 slide, onde o "último" seria o hook. Os arquivos são servidos em `/goviral-assets/<nome>` para a prévia; o renderer os abre direto do disco.
- ✅ **Botão "Melhorar textos" no `/goviral` (opcional)** — um LLM reescreve o painel melhor e mais curto, **no idioma em que o painel está** (não traduz — a regra nº 1 do prompt, porque um prompt em português induzia o modelo a verter painéis em inglês): hook mais afiado (mesma promessa), parágrafos de até ~120 caracteres (mesma ideia, mesma voz) e um **script novo de fecho promovendo o GoViral app** — que vira a última imagem, a mesma que recebe o print de `goviral_assets/`; o fallback do promo também acompanha o idioma do painel. O painel volta REMONTADO para a caixa de colar, revisável e com "desfazer". A distribuição pelas imagens não muda: o enhancer devolve a mesma contagem de parágrafos ou a resposta inteira é descartada. No Groq, o pedido vai com `response_format: json_object` e `reasoning_effort: "none"` (senão um modelo de raciocínio como o Qwen 3.6 gasta o orçamento inteiro em `<think>` e o JSON nem começa); endpoint que rejeite os campos recebe a chamada de novo sem eles, e o `<think>` que sobrar é removido antes do parse. A geração continua determinística e sem LLM; este é o único ponto do fluxo do painel em que um modelo toca no texto, e só quando o botão é clicado. Sem `LLM_API_*` configurado, o botão explica o que falta em vez de fingir que melhorou.

---

## 🎯 O que mudou na v0.9

- ✅ **O painel do goviral colado inteiro vira carrossel** — a nova tela **`/goviral`** ("Colar do painel", no menu) recebe o dashboard como o `Ctrl+A`/`Ctrl+C` entrega: `Hook`, `Script N`, `Position N`, `Paragraph 1/2`. O hook vira a imagem 1 (uma caixa só), cada script vira uma imagem — parágrafo 1 na caixa de cima, parágrafo 2 na de baixo — e o **número de imagens sai do próprio painel**, sem seletor de slides. Antes, chegar nesse resultado eram onze cliques de copiar (um por caixa do painel) e um paste por campo; colar tudo na caixa única também não servia, porque sem os rótulos `Imagem N:` o texto seguia para o LLM redistribuir. Só tema/palavras-chave (busca de fotos) e estilo continuam sendo perguntas — o painel não as responde.
- ✅ **O painel é reconhecido nos caminhos que já existiam** — colado na caixa única do modo automático, entra na mesma regra dos rótulos `Imagem N:`: composição determinística, **sem LLM**, com aviso na prévia. No botão "distribuir" do briefing completo, cada script preenche seu campo (o status diz "Painel do goviral: N imagens"). O formato mais específico é tentado primeiro: "Script 1 / Paragraph 1" não casa com nenhum separador genérico e, sem isso, cada rótulo do painel viraria um slide.
- ✅ **"Conferir o que foi entendido"** — antes de gerar, a tela mostra a distribuição (imagem por imagem, com as duas caixas). O painel é HTML de terceiro: quando o goviral mudar o layout, o parser vai errar — e o erro tem que aparecer aqui, não como um carrossel com texto no slide errado. Reconhecido pela metade não conta: sem o rótulo `Hook` com texto e pelo menos um script com texto, a resposta é "não é painel" e os caminhos de sempre continuam valendo.
- ✅ **Tolerâncias do clipboard** — preâmbulo antes do `Hook` (cabeçalho, "Last updated", "Sign Out") é descartado por posição, sem lista de textos de interface; `Position N` decide a ordem quando presente em todos os scripts; painel sem cabeçalhos `Script N` é dividido pelo `Paragraph 1` (a numeração reinicia a cada script); parágrafo quebrado em várias linhas continua na mesma caixa; um `Paragraph 3` excedente entra na caixa de baixo em vez de criar imagem que o painel não tem.

### O painel na prática

```
Content Dashboard          ← preâmbulo: descartado
Hook
i regret posting consistently and here is why...
Script 1                   ← imagem 2
Position 1
Paragraph 1:
i was consistent, but i was still guessing.        ← caixa de cima
Paragraph 2:
i posted every day with no plan...                 ← caixa de baixo
```

`Hook`/`Gancho`, `Script`/`Roteiro`, `Paragraph`/`Parágrafo` e `Position`/`Posição` são aceitos, com o texto na mesma linha (`Hook: frase`) ou na seguinte. Os rótulos são orientação de montagem — nunca aparecem na imagem.

---

## 🎯 O que mudou na v0.8

- ✅ **O rótulo `Imagem N:` decide, e o LLM sai do caminho** — quando o texto colado traz os rótulos, cada trecho vai para a foto que você indicou e **nenhum composer roda**. Antes isso só valia no botão "distribuir"; colado na caixa única, o mesmo texto ia para o LLM redistribuir. Escrever o rótulo já é a decisão de distribuição — mandar isso para um modelo só cria a chance de ele decidir diferente, e o sintoma disso era o hook aparecendo colado no texto de outro slide. A prévia avisa quantos rótulos foram obedecidos.
- ✅ **A linha em branco é a caixa de baixo, não a imagem seguinte** — dentro de um bloco, uma linha em branco manda o texto seguinte para a **segunda caixa daquela imagem**; o intervalo de **duas** linhas em branco é que separa as imagens. Era a distinção que o roteiro colado já carregava e que o parser jogava fora: toda linha em branco virava imagem nova, então cada script rendia dois slides e o carrossel saía com o dobro de fotos.
- ✅ **O rótulo aceita nota e linha própria** — `Imagem 1 (hook): frase` e `Imagem 2:` com o texto embaixo. A nota entre parênteses é orientação para quem escreve e sai junto com o rótulo. Antes, qualquer uma das duas formas fazia o rótulo **deixar de ser rótulo**: a frase virava preâmbulo (descartada) ou entrava na foto com `Imagem 1 (hook):` escrito nela.
- 🐛 **Todos os slides saíam com o roteiro inteiro** — no composer mock, a limpeza que tirava os espaços duplos das hashtags usava `\s{2,}`, que inclui `\n`: as linhas em branco do texto colado desapareciam, o texto virava um parágrafo só e o mesmo parágrafo era repetido em rotação por todos os slides — hook incluído. É a causa de "o hook juntou com outro texto" quando não há LLM configurado (`LLM_PROVIDER=mock`) e também quando a chamada ao LLM falha, porque o fallback é este mesmo composer. Agora o slide 1 recebe o **primeiro trecho e nada mais**, e cada trecho seguinte vira uma caixa.
- 🐛 **O hook cortado em 70 caracteres no caminho LLM** — a caixa do hook cabe 160 (`HOOK_TEXT_LIMIT`), mas o corte de headline era aplicado **antes** de o slide ser reconhecido como hook: uma frase de 80 caracteres voltava com `…` no meio, alterada sem que a caixa precisasse disso. O corte de 70 continua valendo nos outros slides.
- ✅ **A imagem 1 nunca sai sem texto** — invariante testada contra as quatro formas de o modelo desobedecer ao prompt do slide 1 (apoio a mais, frase no campo errado, papel errado, headline em branco). Se ainda assim sobrar caixa vazia, ela recebe a primeira frase do texto colado, com o motivo no log.
- ✅ **Piso de resolução na busca de fotos** — o Pinterest sem token agora descarta pin que não cobre os 1080×1350 do slide. Um pin de 474×711 era **ampliado** no render e chegava ao feed borrado, com a legenda nítida por cima. O ranking por visão não tinha como reprovar isso: o VLM julga uma thumb de 474px, e a resolução da origem não está na imagem que ele vê (ver [Só foto que cobre o slide](#só-foto-que-cobre-o-slide)).

### O rótulo diz a imagem, a linha em branco diz a caixa

```
Imagem 1 (hook): ninguém acorda às 5h por disciplina

Imagem 2: acorda porque dormiu às 21h

ninguém fala essa parte

Imagem 3: o corpo não negocia sono

você só troca a hora da dívida
```

Esse texto pode ser colado em **qualquer uma** das duas caixas — a única do modo automático ou a de "distribuir" — e produz o mesmo carrossel: três imagens, a primeira com uma caixa (o hook), as outras com duas.

| No texto | O que acontece |
| --- | --- |
| `Imagem N:` no começo da linha | Diz em qual foto o trecho entra. É orientação para a montagem: **nunca** aparece na imagem. Aceita `Foto`, `Slide`, `2.`, `3)` e nota entre parênteses. |
| Linha em branco dentro do trecho | O texto seguinte vai para a **outra caixa** da mesma imagem. |
| Duas linhas em branco (sem rótulo) | Imagem nova. É o que faz o formato antigo — hook, depois pares de linhas — funcionar sem rótulo nenhum. |
| Linha em branco dentro do trecho da **imagem 1** | Nada: a imagem 1 é uma caixa só, então o bloco inteiro vira a frase do hook. |

Com rótulos, o texto **não passa por LLM nenhum** — nem no modo automático. Sem rótulos, o modo automático continua como sempre: o composer (LLM ou mock) fatia o texto. O rótulo é o sinal, e é por isso que ele não é adivinhado: um texto corrido sem rótulo não tem como dizer onde uma imagem termina.

### Só foto que cobre o slide

O render faz `cover` da foto num canvas de 1080×1350. Uma foto menor que isso é **ampliada** — e o resultado é a assinatura visual de post amador: fundo borrado com a legenda nítida em cima.

O ranking por visão não resolve isso, e é importante entender por quê: o VLM recebe uma thumb de ~474px (é o que mantém o custo de tokens baixo), então a resolução da **origem** não está na imagem que ele julga. Ele pode reprovar foto escura, poluída ou com logo; resolução, não. Por isso o piso é aplicado na **busca**:

**O piso mede a ampliação, não a medida bruta de cada lado** (v0.22). Exigir 1080 de largura literais reprovava `1024×1536` — o tamanho mais comum do acervo do Pinterest — por 56px, sendo que o `cover` o ampliaria em **1,055×**, o que ninguém vê. O que importa é `max(1080/largura, 1350/altura)`: até **1,10×** a foto passa, acima disso não. Medido em 2026-08-23 sobre os mesmos 120 pins de `morning routine aesthetic`, a tolerância leva o pool usável de **40 para 71**; os tamanhos recuperados são justamente `1024×1536` (14 pins) e `1000×1500` (12). Entre 1,05× e 1,10× não existe nada no acervo — o degrau é esse, e ir além dele passaria a aceitar arquivo que chega macio de verdade.

| Ordem de preferência | Quando entra |
| --- | --- |
| Retrato **e** cobre o slide com até 1,10× de ampliação | Sempre que o tema tiver acervo para isso. |
| Cobre o slide, em qualquer orientação | Foto grande deitada perde metade da cena no recorte; foto pequena estraga a foto inteira. Entre as duas, a grande. |
| Nada | Acima de 1,10× a fonte devolve menos fotos ou cai no fallback, com o motivo escrito na prévia. O piso não cede. |

Pin sem resolução no payload **não** passa o piso: o pool tem 120 pins e sobra material para exigir prova em vez de dar o benefício da dúvida.

O piso é o próprio tamanho do slide (`SLIDE_WIDTH`×`SLIDE_HEIGHT`) — não há variável nova para configurar. O filtro é feito no pool já recebido, e não no parâmetro `min_resolution` da `pinterest-dl`: lá o corte acontece antes da contagem, então a biblioteca pagina mais vezes para fechar a conta, e o corte dela é o literal, sem a tolerância de ampliação. No Unsplash o problema não existe: a `urls.regular` sai com 1080px de largura e a busca já pede `orientation=portrait`.

---

## 🎯 O que mudou na v0.7

- ✅ **Pinterest sem token, como segunda opção de busca** — `IMAGE_PROVIDER=pinterest_scrape` busca as fotos pela biblioteca [pinterest-dl](https://github.com/sean1832/pinterest-dl), que lê a API interna do site. Não pede credencial nem aprovação, que é o que travava a API oficial: o `/search/pins/` da v5 exige Standard Access. É **opt-in explícito** — o modo `auto` não escolhe scraping sozinho (ver [compliance](#️-limitações-e-compliance)).
- ✅ **A imagem 1 é só o hook** — a primeira foto do carrossel mostra uma caixa e nada mais: a frase que para o scroll, sem texto de apoio e sem CTA. Vale nos três caminhos que produzem slides (roteiro escrito à mão, composer mock e LLM) e sobrevive à edição na prévia, onde os campos de apoio e CTA da imagem 1 aparecem em leitura apenas.
- ✅ **Prompt de roteiro mais específico** — o LLM recebe os tipos de hook nomeados (contrarian, omissão, erro, número, história), o teto de caracteres, a lista do que é proibido no hook (saudação, "neste carrossel vou te mostrar", pergunta genérica) e a regra de uma ideia por slide. Pedir "escreva um hook" devolvia a média da internet; nomear o formato empurra o modelo para uma frase que arrisca alguma coisa.
- 🐛 **Roteiro de 12 slides caía no composer mock** — o `max_tokens` era fixo em 1200 e o JSON chegava cortado no meio de um item; um JSON quebrado descarta o documento inteiro, então o carrossel voltava do mock sem dizer por quê. O orçamento agora cresce com o número de slides.
- 🐛 **A visão falhava com as fotos do Pinterest** — a chamada mandava a **URL** da thumb e deixava o download por conta do endpoint: o servidor da ModelScope (na China) não alcança o `i.pinimg.com` e devolvia `HTTP 400` com `context deadline exceeded` — a mesma chamada que funcionava no Unsplash, cujo CDN responde de lá. Agora a thumb é baixada pelo app e vai como **bytes** (data URI base64), formato que qualquer endpoint OpenAI-compatible aceita. Uma foto que não baixe fica **fora** da chamada em vez de ir como URL, porque uma única URL inalcançável derrubava a avaliação das oito; sem nenhuma foto baixada, a chamada nem sai e o ranking textual assume.
- 🐛 **O hook saía com texto a mais no composer LLM** — o prompt proíbe apoio no slide 1, mas quando o modelo escrevia um mesmo assim o código **colava** essa frase no hook, aplicando a regra pensada para o roteiro manual (lá o apoio é texto do usuário, e descartar seria pior). Vindo do modelo, o apoio é excesso — a informação continua nos outros slides — e agora é **apagado**, como a tabela abaixo sempre prometeu. Um roteiro colado no padrão "duas linhas por script" induzia exatamente isso: o modelo imitava o padrão também no slide 1. Se o modelo inverter os campos (frase no body, headline vazia), o body vira o hook para o slide 1 não sair em branco. No roteiro manual nada muda.

### Buscar fotos no Pinterest sem token

A API oficial v5 do Pinterest só libera o `/search/pins/` com **Standard Access**, que é aprovação manual da Pinterest. Sem ela, este projeto tinha o Unsplash — que resolve o problema da foto, mas não o do *repertório*: o Pinterest é onde mora a estética de photo post que o carrossel imita.

```bash
IMAGE_PROVIDER=pinterest_scrape
```

Não há chave, cota nem conta. A API interna devolve 50 pins por requisição e a biblioteca pagina sozinha até fechar o número pedido, com um `sleep` de 0,2s entre páginas. O pool é de **120 pins** (três requisições, ~4,8s medidos contra ~3,0s de uma só) porque o piso de resolução é estrito e come a maior parte deles: medido em 2026-08-22 na query `morning routine aesthetic`, **11 de 40** pins passavam o piso — contra **71 de 120** com o pool fundo e o piso por ampliação da v0.22.

Do pool de 120 pins, o recorte aplica três correções — duas delas pelos mesmos motivos que já valiam para o Unsplash:

| Correção | Por quê |
| --- | --- |
| **Resolução primeiro** | O slide tem 1080×1350 e o render faz `cover`: uma foto menor é ampliada e chega ao feed borrada, com a legenda nítida por cima. Ver [Só foto que cobre o slide](#só-foto-que-cobre-o-slide). |
| **Retrato primeiro** | O slide é 4:5. Uma foto deitada perde metade da cena no recorte de cover. O Unsplash resolve com `orientation=portrait`; a API interna não tem esse parâmetro, então o filtro é feito aqui, pela resolução que vem em cada pin. Sem retrato suficiente, o pool inteiro vale — foto deitada ainda é melhor que gradiente. |
| **Sorteio dentro do pool** | A busca vem ordenada por relevância e essa ordem é estável: sem sortear, o mesmo tema devolveria as mesmas fotos toda vez — o sintoma que parecia cache no Unsplash e era determinismo da API. O sorteio decide *quais* pins entram; a ordem de relevância é preservada na saída. Fotos que já saíram em carrosséis recentes vão para o fim do sorteio (ver [A mesma hashtag não devolve o mesmo carrossel](#a-mesma-hashtag-não-devolve-o-mesmo-carrossel)). |

O `alt` de cada pin ("a woman sitting on a couch holding a cup") é a mesma forma do `alt_description` do Unsplash, então o [casting por metadado](#casting-hook-com-pessoa-resto-com-cenário) continua funcionando sem VLM configurado.

**Uma armadilha do CDN**, porque ela quebra a visão em silêncio: a URL da foto carrega o tamanho no caminho (`/originals/ab/cd/ef/hash.png`), e a thumb que vai para o VLM troca esse segmento por `474x`. O caminho reduzido serve **só JPEG** — um `.png` ali responde `403`. Por isso a extensão é reescrita junto com o tamanho.

Qualquer falha (rede, mudança de payload, biblioteca ausente) cai no gradiente mock com o motivo escrito no aviso da prévia, igual aos outros clientes.

> A biblioteca está no `requirements.txt` e só é importada quando `IMAGE_PROVIDER=pinterest_scrape`. Nos outros modos ela nem é carregada — o `/health` mostra se o pacote está instalado em `images_diagnostic.pinterest_scrape_installed`.

### A imagem 1 mostra o hook e mais nada

No photo post nativo o primeiro quadro tem uma frase só. O olho tem menos de um segundo ali, e qualquer coisa embaixo da frase divide essa atenção — por isso a imagem 1 é **uma caixa**: o hook, sem apoio e sem CTA.

A regra é aplicada em um lugar só (`enforce_hook_slide`) e vale nos três caminhos que produzem slides:

| Caminho | O que acontece na imagem 1 |
| --- | --- |
| Roteiro por imagem | O bloco inteiro vira a frase. Duas linhas no campo — ou duas caixas separadas por linha em branco — saem coladas numa caixa só, e não como headline + apoio. |
| Composer mock | O slide de hook recebe o **primeiro trecho e nada mais**, sem body e sem CTA. |
| Composer LLM | O prompt proíbe body no slide 1 — e o código apaga se o modelo escrever mesmo assim. O papel do slide 1 também é forçado para `hook`, independente do que o modelo rotule, e a caixa nunca fica vazia: sem texto utilizável, ela recebe a primeira frase do texto colado. |

O apoio que **você** escreveu não é descartado: ele entra na mesma caixa, colado à frase. Um hook comprido é visível e corrigível na prévia; texto que some sem aviso, não. O teto da caixa é de 160 caracteres — acima do limite de uma headline comum (70) justamente para caber quem escreveu duas linhas. O apoio que o **LLM** inventa no slide 1 segue a regra oposta: o prompt o proíbe, então o que vier ali é excesso do modelo e é apagado em vez de colado — colar deixava o hook com texto a mais.

Na prévia, os campos "Texto" e "CTA" da imagem 1 aparecem em leitura apenas, e a gravação limpa os dois de qualquer jeito: oferecer um campo e ignorar o que foi digitado nele seria pior que não oferecer.

---

## 🎯 O que mudou na v0.6

- ✅ **Roteiro por imagem** — em vez de colar o texto inteiro e deixar o LLM fatiar, o formulário agora tem um campo por foto do carrossel: `Imagem 1 (hook)`, `Imagem 2 (problema)`, e assim por diante. O que você cola em cada campo é **exatamente** o que sai naquela imagem, na ordem em que você escolheu. Nenhum LLM reescreve por cima. O modo antigo (colar tudo e deixar fatiar) continua ali, agora como uma escolha explícita.
- ✅ **Colar e distribuir** — se o roteiro do goviral.ai vem numerado (`1.`, `Slide 2:`, `---`), cole tudo na caixa de distribuição e o app separa os blocos nos campos certos. Os marcadores são removidos e o texto fica editável antes de gerar.
- ✅ **Casting de imagens por papel** — a imagem 1 recebe uma foto **com pessoa** e as demais recebem cenário (estética, viagem, comida). É o formato dos photo posts de lifestyle que performam: um rosto para parar o scroll, o resto como b-roll. Configurável em `HOOK_SUBJECT`.
- ✅ **Visão classifica o assunto** — com `VISION_ENABLED=true`, o VLM (Qwen-VL na ModelScope, por exemplo) diz se cada foto tem mulher, homem, pessoa genérica ou só cenário. Esse sinal manda no casting. Sem chave configurada, o casting continua funcionando por busca separada + metadado.

### O roteiro por imagem na prática

```
Imagem 1 (hook)      →  "ninguém acorda às 5h por disciplina"
Imagem 2 (problema)  →  "acorda porque dormiu às 21h
                         (linha em branco)
                         ninguém fala essa parte"
Imagem 3 (CTA)       →  "salva pra começar amanhã"
```

Dentro de um campo, a **linha em branco** manda o texto seguinte para a outra caixa daquela imagem. Sem linha em branco vale a regra curta: a primeira linha é a caixa de cima (o texto grande) e o resto é a de baixo. **A imagem 1 é a exceção**: ela mostra só o hook, então o bloco inteiro vira uma caixa só — sem corpo e sem CTA (ver [A imagem 1 mostra o hook e mais nada](#a-imagem-1-mostra-o-hook-e-mais-nada)). O arraste das caixas sobre a foto continua igual — o modo roteiro decide *o quê* e *onde na sequência*, o arraste decide *onde na foto*.

Blocos em branco são descartados e o carrossel encolhe: se você abrir 6 campos e preencher 4, saem 4 slides. No modo roteiro o app **não** inventa CTA nem hashtag que você não escreveu — o texto é seu.

### Casting: cotas de pessoa, comida e cenário

O problema: uma busca por `"rotina matinal"` devolve xícara, caderno e janela na primeira página — quase nunca o retrato que um hook precisa. Ranquear melhor não resolve, porque a foto de pessoa simplesmente não está no resultado.

A solução tem três camadas, cada uma cobrindo a falha da anterior:

| Camada | Sinal | Vale quando |
| --- | --- | --- |
| **1. Busca em pools** | A query roda separadamente para pessoa, comida (incluindo smoothie/frutas) e cenário geral. Cada foto lembra de qual pool veio. | Sempre — garante candidatos para cada cota pedida. |
| **2. Metadado** | Palavras no `alt`/descrição **da foto** (`woman`, `portrait`, `smoothie`, `fruit`, `comida`…). Conta o primeiro assunto citado e em primeiro plano: depois de um `with`/`com` vem o cenário. | Sem VLM configurado. |
| **3. Visão** | O VLM olha a foto e classifica `woman`, `man`, `person`, `food` ou `scene`. Vence as outras duas camadas. | `VISION_ENABLED=true`. |

O resultado é gravado como `image_id` em cada slide — o mesmo campo que a galeria da prévia edita. Ou seja: o casting é um **palpite inicial**, não uma trava. Discordou? Troque a foto na prévia com um clique.

**A cota limita o foco, não o segundo plano.** "Uma foto de comida" é uma foto *sobre* comida, não qualquer foto em que se veja uma xícara — senão um tema como `rotina matinal`, onde há café em quase toda imagem, esvazia o acervo de cenário e o carrossel passa a repetir foto. Por isso o metadado é lido em três regras: vence quem vem antes ("a man drinking a coffee" é pessoa, "morning coffee on a table" é café), depois de `with`/`com` é cenário ("a bedroom **with** a cup of coffee" é o quarto), e um pedaço do corpo não é um retrato ("woman's hands holding a cup" é b-roll). Vale também no sentido inverso: a legenda descreve *aquela* foto, então uma paisagem que a busca de retrato trouxe por engano serve de cenário mesmo tendo vindo do pool de pessoa.

O casting lê o campo `alt` — o texto que o provider escreveu sobre a foto —, nunca o `title`, que cai na query da busca quando não há legenda. A query descreve a busca, não a foto: lida como metadado, ela faria de comida toda foto sem legenda vinda do pool de comida.

Se uma cota não puder ser atendida, o slide recebe a melhor imagem ainda não usada e um aviso amarelo aparece na prévia — o app diz o que não conseguiu em vez de fingir que deu certo.

---

## 🎯 O que mudou na v0.6

- 🐛 **A etiqueta da linha de baixo comia o rabo dos "g" da linha de cima** — as caixas se sobrepõem de propósito (o passo entre linhas é 1.196× o corpo, a caixa tem 1.48×), e o navegador pinta uma linha inteira — fundo **e** texto — antes de começar a seguinte: o branco da linha seguinte caía sobre o descendente da anterior e o "g" aparecia cortado, como se um pedaço da letra tivesse sido apagado. Não era resto das caixas de quando elas eram separadas; era ordem de pintura. O PNG nunca teve o defeito porque o Pillow desenha em duas passadas — todas as caixas, depois todo o texto. Agora a prévia faz igual: o inline de baixo pinta só as etiquetas (com a tinta transparente) e uma cópia `aria-hidden` do texto desenha só as letras, acima de todas elas. As duas camadas saem da **mesma regra** de CSS e o peso da fonte mora no contêiner que é pai das duas — se elas quebrassem a linha em pontos diferentes, a letra cairia fora da própria caixa.
- ✅ **Uma caixa por linha, do tamanho da linha** — a caixa passou a ser desenhada por *bloco*: uma frase de três linhas virava um retângulo com a largura da linha mais longa, e as linhas curtas ficavam com um vão branco de cada lado. O photo post de referência faz o contrário — **cada linha tem a sua etiqueta**, e a borda acompanha o comprimento daquela linha. O que fazia a versão anterior por linha parecer "serrilhada" não era a ideia, era a geometria: as caixas ficavam separadas. Medido no original, o passo entre linhas (**1.196×** o corpo) é *menor* que a altura de uma caixa (**1.48×**), então as etiquetas se **sobrepõem** ~0.29× e a pilha lê como uma mancha branca contínua. Números todos tirados da referência: folga horizontal 0.45× de cada lado, raio 0.22×.
- ✅ **A linha só quebra perto da margem** — a largura útil subiu de 80% para 88% do canvas, e o teto fixo de linhas por caixa (`4/6/2`) saiu. Ele encolhia a fonte com o slide ainda vazio; o texto agora corre até perto da margem da foto e simplesmente ganha mais uma linha, crescendo para baixo. A fonte só cai quando os blocos somados passariam de 84% da altura do slide — que é o comportamento do editor do TikTok, onde o reajuste é do tamanho da fonte, não do número de caixas.
- 🐛 **Arrastar a caixa reescrevia a quebra do texto** — no CSS a caixa era `width: fit-content` e, ao ser arrastada, virava `position: absolute`. Para um elemento absoluto, `fit-content` mede o espaço **da borda esquerda até o fim do contêiner**: quanto mais à direita a caixa ia, menos largura tinha para calcular, então o texto reencaixava em mais linhas — estreitava na horizontal e crescia na vertical durante o arraste, como se a fonte tivesse mudado. Agora a largura de referência é fixa (`width: max-content` com o mesmo teto de 88%), então mover não reflui o texto. `left`/`top` continuam sendo os únicos valores que o arraste grava.
- 🐛 **`Vision não devolveu JSON utilizável` com HTTP 200** — quatro causas somadas, todas silenciosas. (1) O `max_tokens` era fixo em 900 e a resposta de 8 imagens não cabia: o JSON chegava cortado no meio de um item e o parser descartava o documento inteiro, inclusive as avaliações completas. Agora o orçamento é por imagem e os objetos balanceados são recuperados de uma resposta truncada. (2) Os modelos de raciocínio da ModelScope devolvem o texto em `reasoning_content` e deixam `content` vazio — o parser olhava só para `content`. (3) O aviso não dizia o que tinha voltado; agora loga `finish_reason` e o começo da resposta, e aponta a variante Thinking quando o corte foi por tokens. (4) **Aumentar o orçamento não resolvia sozinho**: numa variante Thinking o raciocínio gasta tudo antes de o JSON começar (`finish_reason=length` com 8.605 caracteres de "The user wants me to evaluate 8 images…"). A chamada agora manda `chat_template_kwargs: {"enable_thinking": false}` — o parâmetro do vLLM, que é o servidor por trás da ModelScope API-Inference. Gateway que não conhece o campo devolve `400` na hora e a chamada é repetida sem ele, então quem já funcionava não quebra.
- ✅ **Cada caixa de texto anda sozinha** — antes o arraste movia headline, corpo e CTA juntos, como um bloco só, e não dava para pôr a pergunta no topo da foto e a resposta embaixo (o layout dos photo posts nativos). Agora cada caixa arrasta separada e grava seu próprio centro (`box_positions`). Uma caixa parada continua no empilhamento do papel; duplo clique devolve qualquer uma delas ao padrão.
- ✅ **Um tamanho de fonte só, para todos os tipos** — headline, corpo e CTA saíam de bases diferentes (68/54/52) e encolhiam cada um por conta própria, então o mesmo texto mudava de tamanho conforme o campo em que fosse colado. Agora todas as caixas partem do mesmo corpo e, se o texto não couber, **todas** reduzem juntas.
- ✅ **Resize por caixa no editor** — um controle por caixa na prévia (50%–250%), que multiplica o tamanho comum e vai junto para o PNG exportado.
- ✅ **Caixas coladas no texto** — a caixa branca era dimensionada pela métrica da fonte (`ascent + descent`), que embute ~35% de espaço morto: sobrava borda em cima e embaixo e o resultado parecia um bloco, não a etiqueta do TikTok. Agora a caixa é medida pela mancha de tinta real do texto. Na prévia, o mesmo bug tinha outra causa: `display:inline` dentro de um flex container é ignorado (o filho é blocado e ocupa a largura toda), então cada caixa ganhou seu próprio contêiner `width: fit-content`.
- 🐛 **Visão cancelada em 20s mesmo com 60 no blueprint** — a visão dividia o `REQUEST_TIMEOUT_SECONDS` com a busca de imagens. Os 20s do log eram o *default do código*, não o valor do painel: a variável não chegava à aplicação, e mesmo chegando o número certo para o Unsplash é curto demais para um VLM. Agora a visão tem `VISION_TIMEOUT_SECONDS` (default `90`) e o gunicorn roda com `--timeout 180`, senão o worker morria antes do fallback.

## 🎯 O que mudou na v0.5

- ✅ **Reposicionamento do texto** — no estilo `sticker`, arraste o texto sobre a foto na prévia. A posição é gravada como fração do canvas (o centro da caixa) e o PNG exportado sai igual à prévia. Duplo clique volta à âncora do papel no roteiro.
- ✅ **Qualificação de imagem por visão (opcional)** — com `VISION_ENABLED=true`, um VLM olha as fotos e devolve nota de relevância **e** a região limpa para o texto, que vira `pos_x`/`pos_y` automaticamente. Funciona em qualquer endpoint OpenAI-compatible com `image_url` (ex.: ModelScope API-Inference, que tem tier gratuito). Desligado por padrão; qualquer falha cai no ranking textual.
- 🐛 **Unsplash repetia as mesmas fotos** — `/search/photos` ordena por relevância de forma estável, então a mesma query devolvia sempre a página 1. Parecia cache do app; era determinismo da API. Agora a página é sorteada dentro das 5 primeiras a cada busca, com reentrada quando a query tem acervo curto.

### Como as imagens são qualificadas — dois modos

**Padrão (`RANKING_ENABLED`) — só texto.** O LLM recebe título/descrição de cada foto mais o `raw_text` e devolve uma ordem. Nenhum pixel sai daqui. Consequência: quando o `alt_description` do Unsplash vem vazio ou genérico, o ranking julga quase no escuro. Qwen, Llama ou GPT nesse papel trabalham só com metadado.

**Opcional (`VISION_ENABLED`) — o modelo olha a foto.** Um VLM recebe as imagens e devolve três coisas:

1. **Nota de relevância** olhando a imagem — penaliza foto com texto/logo embutido, muito escura ou poluída no centro, coisas que o metadado nunca revela.
2. **Onde o texto cabe.** O estilo sticker desenha caixas brancas por cima da foto. Sem visão, a posição vem da âncora do papel no roteiro e às vezes cai em cima do rosto. O modelo escolhe uma zona limpa (`top`, `bottom-left`, …) e ela vira `pos_x`/`pos_y` no slide — o mesmo campo que o arraste na prévia grava, então você continua corrigindo por cima.
3. **O assunto da foto** (`woman`, `man`, `person`, `scene`) — é o sinal mais forte do [casting](#casting-hook-com-pessoa-resto-com-cenário), que decide qual foto abre o carrossel. Uma leitura da foto de banco, não identificação de indivíduo: serve só para saber se há alguém em cena.

Pedir uma **zona nomeada** em vez de coordenadas cruas é o que torna a saída estável: VLM erra número solto, mas acerta "topo/meio/base".

Precisa de um endpoint OpenAI-compatible que aceite `image_url`. O **ModelScope API-Inference** serve e tem tier gratuito (~2.000 chamadas/dia, exige conta vinculada à Alibaba Cloud):

```bash
VISION_ENABLED=true
VISION_API_BASE_URL=https://api-inference.modelscope.cn/v1
VISION_API_KEY=ms-xxxxxxxx
VISION_MODEL=Qwen/Qwen3-VL-235B-A22B-Instruct   # ou PaddlePaddle/ERNIE-4.5-VL-28B-A3B-Paddle
```

O ID é **namespaced por organização** no ModelScope. Sem o prefixo, a resposta é 404 e a aplicação cai no ranking textual sem quebrar — confira em `/health` → `vision_diagnostic`.

Dois cuidados de projeto: as fotos vão na versão **pequena** (~400px, `urls.small`), baixadas pelo app e embutidas como **base64** na chamada — 400px basta para julgar composição (a cheia multiplicaria os tokens de visão), e mandar a URL deixaria o download por conta do endpoint, que nem sempre alcança o CDN (o servidor da ModelScope não acessa o `i.pinimg.com` do Pinterest); e no máximo **8 imagens por chamada**, já que a chamada é síncrona dentro do `POST /generate`. Timeout, JSON ilegível, `image_id` alucinado ou visão desligada — qualquer um desses cai no ranking textual de sempre.

A visão tem **timeout próprio** (`VISION_TIMEOUT_SECONDS`, default `90`), separado do `REQUEST_TIMEOUT_SECONDS` da busca de imagens. Enquanto os dois eram o mesmo número, o valor dimensionado para o Unsplash (20s) cancelava o VLM antes da primeira resposta — o log dizia `não respondeu em 20s` e o carrossel caía no ranking textual sem nada estar configurado errado. Dois timeouts porque as duas chamadas não têm nada a ver uma com a outra: uma é um GET de JSON, a outra é um modelo olhando 8 fotos. O worker do gunicorn roda com `--timeout 180`, que precisa ficar acima do timeout da visão para o fallback ter chance de acontecer — worker morto não faz fallback.

#### Quando o log diz `Vision não devolveu JSON utilizável`

HTTP 200 e nenhum veredicto significa que a chamada funcionou e a **resposta** é que não serviu. O aviso agora carrega o `finish_reason` e o começo do que voltou, que é o suficiente para separar os três casos:

| No log | O que aconteceu | O que fazer |
|--------|-----------------|-------------|
| `finish_reason=length` | A resposta foi cortada no limite de tokens. Numa variante **Thinking** o raciocínio consome o orçamento inteiro e o JSON nem começa. | O pedido já manda `enable_thinking: false`; se o log insistir, o provider ignorou o parâmetro — trocar `VISION_MODEL` pela variante **Instruct**. Se a resposta chegou parcial, os itens completos já são aproveitados sozinhos. |
| `finish_reason=stop` + prosa | O modelo respondeu em texto ("Claro! A primeira foto…") em vez de JSON. | Um VLM mais fraco no seguimento de instrução — trocar de modelo. |
| `(resposta vazia)` | Nem `content` nem `reasoning_content` vieram preenchidos. | Verificar cota/limite do provider. |

O orçamento de tokens é calculado por imagem (`700 + 220 × nº de imagens`), não fixo: um veredicto ocupa ~60 tokens e as 8 imagens da chamada não cabiam nos 900 que havia antes. Uma resposta truncada ainda é aproveitada — cada objeto `{...}` completo é lido isoladamente, então perder o último item não custa os outros sete.

Orçamento maior, porém, não salva um modelo de raciocínio: o pensamento cresce junto e continua estourando o teto. Por isso o pedido carrega `chat_template_kwargs: {"enable_thinking": false}`, a forma [documentada pelo vLLM](https://docs.vllm.ai/en/stable/features/reasoning_outputs) de desligar o modo Thinking na série Qwen3 — e o vLLM é o servidor por trás da ModelScope API-Inference. Um gateway que não aceite o campo responde `400` imediatamente, e aí a chamada é refeita sem ele: o custo do experimento é um round-trip que falha rápido, não o timeout de 90s.

Modelos **text-to-image** (Qwen-Image, FLUX, Stable Diffusion) são outra categoria: eles *geram* a foto em vez de qualificar, e substituiriam o Unsplash. Não estão implementados.

---

## 🎯 O que mudou na v0.4

- ✅ **Estilo `sticker` (padrão)** — texto preto em caixas brancas arredondadas, uma por linha, sobre a foto sem escurecer. É o formato de legenda nativo dos photo posts do TikTok.
- ✅ **TikTok Sans empacotada** — `static/fonts/sticker-{bold,regular}.ttf` (SemiBold/Medium), a tipografia oficial do TikTok. Sem isso o servidor caía na Liberation Sans, e a tipografia era o que ainda destoava do visual dos photo posts.
- ✅ **Roteiro viral** — os slides são ordenados na estrutura de 3 atos (`hook → problema → agitação → valor → prova → CTA`). Cada slide carrega um `role`, e o `role` decide onde o texto é posicionado na imagem.
- ✅ **Prompt de roteirista no Groq** — o LLM reordena e encurta o texto colado seguindo os tipos de hook e as regras de escrita de script viral, em vez de só fatiar o texto.
- 🐛 **Fontes no Docker** — a imagem `python:3.11-slim` não traz nenhuma fonte TrueType, então o Pillow caía na fonte bitmap padrão e renderizava os slides com texto minúsculo. Agora `fonts-liberation` e `fonts-dejavu-core` são instaladas.
- 🐛 **Texto duplicado** — headline e body recebiam a mesma frase quando o parágrafo tinha uma só sentença.
- 🐛 **Emoji virava tofu (`□`)** — as fontes do sistema não têm glifo de emoji; agora o emoji é removido do PNG e preservado na legenda/Markdown.
- 🐛 **Conflito de merge** — `.env.example` estava commitado com marcadores `<<<<<<< HEAD`.

---

## 🎬 Estrutura do roteiro viral

O texto colado é reorganizado nesta ordem (baseada na estrutura de script viral em 3 atos):

| Papel | Função no carrossel |
|-------|---------------------|
| `hook` | Para o scroll no primeiro segundo. **Uma caixa só** — sem texto de apoio e sem CTA. Ancorado embaixo. |
| `problem` | Nomeia a dor do público. |
| `agitation` | Amplia a consequência de não resolver. |
| `value` | A entrega concreta — uma ideia por slide. |
| `proof` | Número, resultado ou prova de que funciona. |
| `cta` | Uma única ação clara. Centralizado, é o único slide com CTA. |

A distribuição se adapta ao nº de slides — 3 slides viram `hook → value → cta`; 6 ou mais recebem a estrutura completa, com o miolo em slides de `value`.

---

## 🔌 Sobre o goviral.ai e a geração local

O `content.goviralai.app` **não possui API pública** — responde `HTTP 403` a qualquer requisição programática e não publica documentação de desenvolvedor. A autenticação é uma sessão Discord presa ao navegador.

Reaproveitar essa sessão no servidor significaria repassar seus cookies, ou seja, automação de login não autorizada — exatamente o que o escopo deste projeto proíbe e o que pode derrubar sua conta. O fluxo principal agora é **gerar o conteúdo aqui**, via endpoint LLM OpenAI-compatible. Colar o painel continua disponível como importação compatível, sem qualquer chamada ou login automático no goviral.ai.

---

## ✨ Funcionalidades do MVP

- Landing page com geração direta de roteiro e importação opcional do goviral.ai.
- **Tela "Gerar roteiro" (`/goviral`)** — briefing, público, idioma e nº de imagens viram um painel completo via LLM; tema e palavras-chave visuais são preenchidos para a busca de fotos e o texto fica editável antes da montagem.
- **Importação do painel (`/goviral`)** — o dashboard do goviral colado inteiro ainda vira o carrossel: hook + um script por imagem, nº de imagens decidido pelo painel, prévia da distribuição antes de gerar.
- Formulário com **um campo de roteiro por imagem** (rotulado pelo papel do slide) ou textarea única, mais tema, estilo, nº de slides, idioma e keywords.
- **Rótulo `Imagem N:` no texto colado dispensa o LLM** — vale nas duas caixas de texto; a linha em branco dentro do trecho separa as duas caixas da imagem. O **painel do goviral** (Hook + Script + Paragraph) é reconhecido do mesmo jeito, sem rótulo nenhum.
- Botão "distribuir" que divide um roteiro colado entre os campos, entendendo `Imagem N:` (com nota entre parênteses ou sozinho na linha), `2.`, `---`, o intervalo de duas linhas em branco e parágrafos.
- **Casting por papel**: imagem 1 sempre com pessoa (hook), demais com cenário — via busca separada, metadado da foto e visão.
- Composição de carrossel via TextComposer (mock determinístico ou LLM); no modo por imagem — e em qualquer texto colado com rótulos —, sem LLM no caminho do texto.
- **Imagem 1 sempre com o hook sozinho, e nunca em branco** — uma caixa, sem texto de apoio e sem CTA, nos três caminhos de composição.
- Ordenação no roteiro viral de 3 atos (`hook → problema → agitação → valor → prova → CTA`).
- Renderização estilo sticker do TikTok — caixas brancas arredondadas com texto preto.
- Busca de imagens via Pinterest **sem token** (`pinterest-dl`), via **Instagram sem token** (hashtag ou @perfil), via Unsplash ou mock — combinável e escolhível **por geração**. Em Instagram + Pinterest, a quantidade de fotos do Instagram também é escolhida por geração (1 foto para o hook é o padrão).
- **Piso de resolução na busca sem token** — só foto que cobre o slide sem ser ampliada, com degradação em ordem quando o tema não tem acervo.
- Ranking opcional de imagens por endpoint LLM (com fallback determinístico).
- Qualificação por **visão** opcional (VLM): nota olhando a foto + posição automática do texto + assunto da foto (pessoa/cenário) para o casting.
- Prévia do carrossel com slides editáveis (headline, body, CTA por slide) e o papel de cada slide visível.
- Reposicionamento e tamanho de **cada caixa de texto** por arraste/controle na prévia (estilo `sticker`), refletidos no PNG exportado.
- Galeria miniatura por slide para troca de imagem.
- Exportação em três formatos:
  - **ZIP** — todos os slides PNG + Markdown anexo.
  - **PNG** — slide único (primeiro).
  - **Markdown** — texto plano com hashtags e atribuição.
- Health check sem expor segredos.
- Funciona em modo **mock** sem credenciais externas.

Fora do escopo (conforme PRD v0.2): publicação automática, automação de login via Discord, geração de vídeos, banco de imagens próprio. A busca de fotos sem token (`IMAGE_PROVIDER=pinterest_scrape`) é a única exceção ao "sem scraping" original, e é opt-in — ver [Limitações e compliance](#️-limitações-e-compliance).

---

## 🚀 Execução rápida (modo mock)

```bash
# 1. Configurar ambiente (defaults mock — funciona sem credenciais)
cp .env.example .env

# 2. Rodar com Docker
docker compose up --build

# 3. Abrir em http://localhost:5000
```

Sem Docker (desenvolvimento local):

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python run.py
```

### Fluxo de uso

1. No ViralPost Studio (`http://localhost:5000/goviral`), descreva a ideia, os fatos e o público. Escolha idioma, número de imagens (5-6 é o padrão) e se o roteiro deve mencionar o Go Viral app.
2. Clique em **Gerar hook e scripts**, revise o painel devolvido e ajuste tema, palavras-chave e estilo visual.
3. Em **Fonte das fotos**, escolha **Instagram + Pinterest** e defina quantas fotos vêm do Instagram. Para usar uma pessoa no hook e variar o restante, deixe **1 foto** e escreva `@perfil` junto do tema/palavras-chave; o Pinterest recebe apenas os termos visuais.
4. Clique em **Gerar carrossel**. O texto já vem distribuído: hook sozinho na primeira imagem e duas caixas em cada script.
5. Se você já tem um painel pronto, cole-o na mesma caixa e use **Conferir o que foi entendido** antes de gerar. Como alternativa, no ViralPost Studio (`http://localhost:5000/create`), escolha o nº de slides (3/6/9/12) e como entregar o texto:
   - **Roteiro por imagem** (padrão) — um campo por foto, rotulado com o papel do slide: *Imagem 1 (hook)*, *Imagem 2 (problema)*, e assim por diante. Dentro de um campo, pule uma linha para mandar o texto seguinte para a outra caixa daquela imagem; sem linha em branco, a primeira linha vira o texto grande e o resto vira o apoio — menos na **imagem 1**, que sai como uma frase só (o hook, sem apoio e sem CTA). Nada de LLM no meio: o que você escreve é o que sai.
   - **Distribuir de uma vez** — dentro do modo por imagem, abra "Colar o roteiro inteiro e distribuir", cole tudo e clique no botão. O servidor divide por `Imagem N:`, `2.`, `---`, intervalo de duas linhas em branco ou parágrafos e preenche os campos, que continuam editáveis.
   - **Texto corrido** — cole tudo numa caixa só e deixe o LLM estruturar. Se você escrever `Imagem 1:`, `Imagem 2:`… na frente dos trechos, o LLM **não entra**: cada trecho vai para a foto que você indicou (ver [O rótulo diz a imagem, a linha em branco diz a caixa](#o-rótulo-diz-a-imagem-a-linha-em-branco-diz-a-caixa)).
6. Preencha tema, estilo (**sticker** recomendado — ou quote/list/tutorial/story) e as palavras-chave da busca de imagens.
7. Escolha quantas fotos devem mostrar pessoas/modelos e quantas devem mostrar comida. A cota de pessoas inclui a imagem 1 (hook); os demais slides são preenchidos por comida e cenário geral conforme as quantidades.
8. Clique em "Gerar carrossel". Com o Qwen-VL configurado, a classificação visual confirma pessoa, comida e cenário; sem ele, o app usa metadados e o pool da busca.
9. Na prévia, cada slide mostra seu papel e de onde veio a foto do hook (visão, metadado ou busca). Edite os textos e troque a imagem pela galeria.
10. No estilo `sticker`, **arraste cada caixa** sobre a foto para reposicionar (duplo clique volta ao padrão) e use o controle de tamanho de cada caixa se quiser texto maior. Clique em "Salvar edições" para gravar.
11. Exporte: **ZIP** (carrossel completo) ou **PNG** (slide único) ou **Markdown** (texto).

---

## ⚙️ Variáveis de ambiente

| Variável | Default | Descrição |
|----------|---------|-----------|
| `FLASK_ENV` | `development` | Ambiente Flask |
| `SECRET_KEY` | `dev-insecure-change-me` | **Definir em produção** |
| `DEBUG` | `true` | Modo debug |
| `IMAGE_PROVIDER` | `auto` | De onde vêm as fotos: `auto`, `pinterest_scrape`, `unsplash`, `instagram_scrape`, `instagram_pinterest`, `unsplash_pinterest` ou `mock`. O seletor "Fonte das fotos" dos formulários vence este valor por geração |
| `UNSPLASH_ACCESS_KEY` | (vazio) | Access Key do Unsplash — a **única** fonte de imagens com chave. Vazio (com `auto`) → mock |
| `APIFY_TOKEN` | (vazio) | Token da [Apify](https://apify.com): roda um **actor** que raspa o Instagram com sessão própria e devolve dataset estruturado. É o único transporte com chance na busca por hashtag, e **vence** o `SCRAPEDO_TOKEN` quando os dois existem. No modo combinado, a UI controla a quantidade exata de itens |
| `APIFY_ACTOR` | `apify~instagram-scraper` | Qual actor rodar (id com **til** no lugar da barra). Cobre hashtag e `@perfil` |
| `SCRAPEDO_TOKEN` | (vazio) | Token do [Scrape.do](https://scrape.do): as mesmas chamadas da API web saem pelo gateway deles (proxies residenciais, `super=true`, 10x créditos). **Não** vence o muro da hashtag — é gate de endpoint; serve ao `429` do caminho `@perfil` |
| `LLM_PROVIDER` | `mock` | `mock` ou `openai_compatible` |
| `LLM_API_BASE_URL` | (vazio) | Endpoint OpenAI-compatible (ex.: `https://api.groq.com/openai/v1`) |
| `LLM_API_KEY` | (vazio) | Token do LLM (ex.: `gsk_...` para Groq) |
| `LLM_MODEL` | (vazio) | Nome do modelo. Ex.: `qwen/qwen3.6-27b`, `llama-3.3-70b-versatile`, `gpt-4o-mini` |
| `RANKING_ENABLED` | `true` | Liga/desliga ranking de imagens (reusa LLM) |
| `HOOK_SUBJECT` | `woman` | Casting da imagem 1: `woman`, `person` ou `off` (desliga o casting) |
| `HOOK_QUERY_HINTS` | (auto) | Termos da busca de retrato. Vazio → `<HOOK_SUBJECT> portrait lifestyle aesthetic` |
| `SCENE_QUERY_HINTS` | `aesthetic lifestyle travel interior workspace` | Termos da busca do cenário geral; comida usa um pool próprio |
| `VISION_ENABLED` | `false` | Ranking **olhando** a foto + posição automática do texto |
| `VISION_API_BASE_URL` | (herda `LLM_*`) | Endpoint OpenAI-compatible com suporte a `image_url` |
| `VISION_API_KEY` | (herda `LLM_*`) | Token do provider de visão |
| `VISION_MODEL` | (vazio) | ID do VLM. **Sem default** — ex.: `Qwen/Qwen3-VL-235B-A22B-Instruct` |
| `REQUEST_TIMEOUT_SECONDS` | `20` | Timeout HTTP da busca de imagens e do LLM de texto |
| `VISION_TIMEOUT_SECONDS` | `90` | Timeout só do VLM — separado porque o modelo olha até 8 fotos por chamada |
| `SESSION_TTL_MINUTES` | `60` | TTL dos projetos em memória |
| `SLIDE_WIDTH` | `1080` | Largura do slide PNG |
| `SLIDE_HEIGHT` | `1350` | Altura do slide PNG (4:5 = TikTok/Instagram) |
| `SLIDE_FONT_BOLD` | (auto) | Caminho para um `.ttf` bold. Vazio → detecção automática |
| `SLIDE_FONT_REGULAR` | (auto) | Caminho para um `.ttf` regular. Vazio → detecção automática |

**Compatibilidade reversa:** variáveis `RANKING_*` antigas (`RANKING_PROVIDER`, `RANKING_API_BASE_URL`, `RANKING_API_KEY`, `RANKING_MODEL`) ainda funcionam e mapeiam para `LLM_*`.

Nenhum valor secreto é commitado. Tokens nunca cruzam para o frontend.

### De onde vêm as imagens

Com `IMAGE_PROVIDER=auto` (o default), a escada é `UNSPLASH_ACCESS_KEY` → **mock** (gradientes SVG sintéticos). Sem a chave, o carrossel sai com gradientes coloridos em vez de fotos.

A API oficial v5 do Pinterest **foi removida na v0.15**: o `/search/pins/` dela exige **Standard Access** (aprovação manual da Pinterest) que este projeto nunca teve, então aquele degrau da escada nunca chegou a buscar nada. `PINTEREST_ACCESS_TOKEN` e `PINTEREST_API_BASE_URL` não são mais lidas.

O Unsplash não exige aprovação — crie um app em [unsplash.com/oauth/applications](https://unsplash.com/oauth/applications) e copie a **Access Key**. Para fotos do Pinterest, `IMAGE_PROVIDER=pinterest_scrape` busca **sem token**, pela API interna do site (ver [Buscar fotos no Pinterest sem token](#buscar-fotos-no-pinterest-sem-token)). Ele nunca entra sozinho no modo `auto` — é escolha explícita, com as [ressalvas de compliance](#️-limitações-e-compliance) que vêm junto.

No modo `instagram_pinterest`, o campo **Fotos do Instagram no modo combinado** controla a mistura. O valor padrão é `1`: o actor busca uma foto do perfil/hashtag para o hook e o Pinterest completa o b-roll. Se a query contém `@perfil`, o handle não é repassado ao Pinterest; se contém `#hashtag`, o `#` sai, mas a palavra continua na busca complementar. A escolha é por geração e não exige variável de ambiente nova.

Os campos **Fotos com pessoas/modelos** e **Fotos de comida** também valem por geração e independem da fonte escolhida. O padrão continua sendo `1` pessoa (o hook) e `0` comida. Quando comida é pedida, a busca ganha um pool próprio com termos de refeições, smoothie, frutas e bebidas; o cenário geral deixa de pedir `food` por padrão. A soma das duas cotas nunca ultrapassa o número real de slides.

O piso de qualidade é o tamanho final do slide. Pinterest e Instagram descartam qualquer origem comprovadamente menor que `SLIDE_WIDTH`×`SLIDE_HEIGHT`; medida ausente também não passa. O Unsplash entrega uma transformação do CDN no tamanho final, com qualidade `85`. Assim o renderer não precisa ampliar uma foto pequena para chegar a 1080×1350.

**Por que a mesma query devolve fotos diferentes agora:** o `/search/photos` do Unsplash ordena por relevância e essa ordem é estável — a página 1 de "café da manhã" é sempre a mesma. Não havia cache no app; era determinismo da API. Cada busca agora sorteia uma página entre 1 e 5 (`UnsplashClient._PAGE_WINDOW`), o que renova o resultado sem cair em fotos irrelevantes. A página escolhida aparece no log `INFO`. Se a query tem acervo curto e a página sorteada vem vazia, a busca reentra dentro do `total_pages` em vez de cair no gradiente mock.

Para confirmar o que está ativo:

```bash
curl -s http://localhost:5000/health | python -m json.tool
# providers.images        → "pinterest_scrape" | "unsplash" | "instagram_scrape"
#                           | "instagram_pinterest" | "unsplash_pinterest" | "mock"
# providers.casting       → "woman" | "person" | "off"
# providers.vision        → "configured" | "off"
# images_diagnostic.using_mock → true quando o carrossel sai com gradiente
# images_diagnostic.pinterest_scrape_installed → o pacote pinterest-dl está instalado?
# images_diagnostic.apify_token_set → transporte do Instagram com chance na hashtag
# vision_diagnostic.vision_model_value → o id do VLM, causa comum de 404
```

> O `.env` é lido pelo `python-dotenv` no app factory, então `python run.py` e `docker compose up` enxergam as mesmas variáveis. Variáveis reais do ambiente (Render, docker-compose) têm prioridade sobre o arquivo.

---

## 🗂️ Estrutura do projeto

```
.
├── app/
│   ├── __init__.py
│   ├── main.py                # Flask app factory
│   ├── config.py              # Settings (env)
│   ├── forms.py               # WTForms (BriefingForm + SlideEditForm)
│   ├── adapters/
│   │   ├── text_composer.py    # TextComposer (mock + LLM)
│   │   ├── script_parser.py    # Roteiro por imagem — blocos → slides (sem LLM)
│   │   ├── goviral_parser.py   # Painel do goviral (Hook/Script/Paragraph) → blocos
│   │   ├── pinterest_client.py # Pinterest v5 + Pinterest/Instagram sem token + Unsplash + Mock
│   │   ├── ranking_provider.py # Inference (LLM) + Mock
│   │   └── vision_provider.py  # VLM — nota + posição do texto + assunto da foto
│   ├── services/
│   │   ├── generation.py      # Orquestração do carrossel
│   │   ├── casting.py         # Cotas por slide (pessoa, comida, cenário)
│   │   ├── recent_media.py    # Fotos já usadas — não repetir na próxima geração
│   │   ├── session_store.py   # Persistência leve (TTL)
│   │   └── slide_renderer.py  # Pillow — overlay de texto em imagem
│   └── routes/
│       ├── main.py            # /
│       ├── create.py          # /create, /script/split
│       ├── goviral.py         # /goviral, /goviral/parse — colar o painel inteiro
│       ├── generate.py        # /generate, /rank
│       ├── preview.py         # /preview/<id>, /edit, /export
│       └── health.py         # /health
├── templates/                 # Jinja2 (base, index, create, preview, health, error)
├── static/                    # CSS, JS
├── tests/                     # pytest
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── requirements-dev.txt
├── .env.example
├── .dockerignore
├── .gitignore
└── run.py
```

---

## 🧪 Testes

```bash
pip install -r requirements-dev.txt
pytest -v tests/
```

Cobertura (511 testes):
- **Pessoa fixada** — round-trip de gravar/ler/esquecer em `instance/pinned_person.json`; URL do pin canonizada (domínio regional e sufixos viram `www.pinterest.com/pin/<id>/`); foto que não é pin (Unsplash, mock, goviral_assets) não é fixável e a rota explica com 422; `related()` do cliente de scrape mapeia os pins para a forma do app, aplica o piso de resolução e devolve `[]` em falha (sem mock — quem chama tem fallback melhor); com o checkbox ligado o pool de hook vem dos relacionados (uma query só, a de cenário) e o slide 1 recebe uma foto deles; ninguém fixado, provider sem `related`, relacionados vazios/erro e casting desligado caem na busca de sempre com o motivo nos avisos; com o checkbox desligado nada muda; o formulário carrega o checkbox até o serviço.
- **Painel do goviral** — o dashboard colado com `Ctrl+A` vira um bloco por imagem (hook numa linha só, parágrafos nas duas caixas); preâmbulo antes do `Hook` descartado sem lista de interface; rótulos nunca chegam ao slide; texto na mesma linha do rótulo ou na seguinte; rótulos das duas colunas antes dos dois textos; `Position` decidindo a ordem; painel sem cabeçalho `Script` dividido pelo `Paragraph 1`; parágrafo multi-linha na mesma caixa; `Paragraph 3` na caixa de baixo; reconhecido pela metade (sem `Hook`, sem texto, só scripts) responde "não é painel"; `Imagem N:` continua sendo do `labeled_blocks`; e as rotas — `/goviral` gera sem perguntar nº de slides, 422 com motivo quando não é painel, `/goviral/parse` mostra a distribuição, o "distribuir" do briefing entende o painel e o painel na caixa única pula o composer.
- **TextComposer** — split em slides, hashtags, texto curto, texto vazio, e as linhas em branco do texto colado sobrevivendo à limpeza das hashtags (colapsá-las fazia todos os slides saírem com o roteiro inteiro).
- **Rótulo `Imagem N`** — nota entre parênteses e rótulo sozinho na linha continuam sendo rótulo; hora no começo da linha (`5:30 da manhã`) não é rótulo; `labeled_blocks` só responde quando os rótulos existem; rótulo digitado dentro do campo não chega ao slide; texto colado com rótulos pula o composer, mantém a ordem e avisa quantos rótulos foram obedecidos, e texto sem rótulo continua indo para o composer.
- **Caixa vs. imagem** — linha em branco dentro do bloco separa as duas caixas daquela imagem, duas linhas em branco separam as imagens, uma caixa de duas linhas sai como uma frase, e no bloco da imagem 1 a linha em branco não cria segunda caixa.
- **Roteiro por imagem** — primeira linha vira headline e o resto o body, rótulos `Imagem N:` removidos, campo vazio herda o papel, blocos além do nº de slides descartados, hashtags e CTA preservados.
- **A imagem 1 é uma caixa só** — o bloco de duas linhas vira uma frase (sem virar headline + apoio) e o hook não é cortado no limite de headline, no roteiro manual **e** no caminho LLM (onde o corte de 70 vinha antes de o slide ser reconhecido como hook); o composer mock devolve o hook sem body nem CTA, com o primeiro trecho e nada mais, e mantém as duas caixas nos outros slides; no LLM o body e o CTA do slide 1 são apagados mesmo quando o modelo os escreve **sem colar o apoio na frase** (a frase mandada no lugar da headline ainda vira o hook), o papel do slide 1 é `hook` independente do que o modelo rotule, e o slide 1 nunca sai sem texto nas quatro formas de o modelo desobedecer ao prompt; a prévia entrega os campos de apoio e CTA da imagem 1 em leitura apenas e a gravação limpa os dois; um hook longo continua validando no formulário de edição.
- **Distribuição do roteiro colado** — separadores `Imagem N:`, `2.`, `---` e parágrafo; teto no nº de slides com o total encontrado reportado; texto vazio e contagem inválida.
- **Casting** — hook recebe pessoa por visão, por metadado (`alt_description`) e por pool de busca, nessa ordem; cotas ajustáveis de pessoa e comida chegam aos slides; smoothie/frutas/bebidas contam como comida; a cota olha o foco da legenda e não a menção (café ao fundo não tira a foto do cenário, café em primeiro plano continua comida, pessoa com xícara ainda serve de hook), a legenda da foto vence o pool que a trouxe, e a query no `title` não é lida como legenda; categorias são intercaladas e fotos únicas vencem repetição; aviso quando uma cota não pode ser atendida; `HOOK_SUBJECT=off` desliga a restrição por assunto.
- **Roteiro viral** — distribuição de papéis por nº de slides, ordem `hook…cta`, CTA só no fecho, sem texto duplicado entre headline e body.
- **SlideRenderer** — resolução de fonte TrueType, auto-ajuste do corpo da fonte, caixas brancas do estilo sticker, ausência de overlay escuro, posição do hook vs. valor, quebra de palavra longa, remoção de emoji.
- **Uma caixa por linha** — cada linha do bloco ganha uma caixa com a largura da própria linha (linha curta não herda a largura da longa); as caixas se sobrepõem para a pilha sair contínua, sem vão entre elas; headline e corpo continuam sendo dois blocos separados; a altura da caixa não muda por a linha ter ou não descendente.
- **Duas camadas na prévia** — a camada de baixo pinta as etiquetas com a tinta transparente e a de cima só as letras, as duas saindo da mesma regra de CSS e com o peso da fonte no contêiner comum (peso diferente entre elas quebraria a linha em outro ponto); o estilo sticker emite a cópia `aria-hidden` no HTML e os outros estilos não.
- **Quebra de linha por altura** — a fonte só encolhe quando os blocos passariam da altura útil do slide (não por contar linhas), e nenhuma palavra é descartada quando o texto cresce.
- **Tamanho uniforme** — headline, corpo e CTA saem no mesmo corpo de fonte; texto longo encolhe as três caixas juntas, nunca uma só.
- **Caixa colada no texto** — a geometria bate com a do photo post de referência (passo entre linhas menor que a caixa, folga lateral proporcional ao corpo da fonte), e o `box_scale` aumenta a caixa junto com a fonte.
- **Reposicionamento** — `pos_x`/`pos_y` vencem a âncora do papel, clamp dentro do canvas, slide sem posição mantém o comportamento antigo, e cada caixa (`box_positions`) move-se sem arrastar as outras.
- **Pinterest mock** — geração de SVGs sintéticos.
- **Pinterest sem token** — mapeamento do pin para a forma que o app usa (id como string, link do pin, `alt` alimentando o casting por metadado), thumb `474x` com a extensão reescrita para `.jpg` (o caminho reduzido do CDN não serve PNG), retrato preferido quando há retrato suficiente e pool inteiro quando não há, resolução ausente que não derruba a seleção, ponto de corte sorteado entre buscas iguais, uma requisição por busca, timeout vindo das settings, e fallback com motivo em falha, resultado vazio, pin sem `src` e biblioteca não instalada.
- **Piso de resolução** — pin menor que o slide fica de fora; foto grande deitada vence foto pequena em pé; sem acervo em alta o piso permanece estrito e a fonte cai no fallback com motivo; pin sem resolução não passa o piso; o Unsplash pede o tamanho final ao CDN; o piso vem de `SLIDE_WIDTH`×`SLIDE_HEIGHT`; e o `min_resolution` da biblioteca continua em `(0, 0)`, para a busca não paginar dentro do `POST /generate`.
- **Escolha do provider** — `IMAGE_PROVIDER` default `auto` e valor desconhecido caindo em `auto` (inclusive o `pinterest_v5` removido); o scraping só entra quando escolhido, nunca no `auto`; `auto` prefere Unsplash e cai no mock sem chave; `mock` ignora a chave configurada; escolha impossível (Unsplash sem chave) desce a escada em vez de devolver um cliente quebrado; e um `PINTEREST_ACCESS_TOKEN` sobrando no ambiente não vira cliente nem desvia a escada.
- **Prompt do roteiro** — a regra do hook sozinho e a ordem dos papéis chegam no prompt, e o orçamento de tokens cresce com o nº de slides (o teto fixo cortava o JSON de 12 slides).
- **Unsplash** — rotação de páginas entre buscas iguais, reentrada quando a página sorteada passa do fim do acervo, motivo do fallback por status HTTP.
- **Ranking** — correlação com `raw_text`, fallback sem corpus.
- **Visão (VLM)** — baixa a thumb (não a foto cheia) e manda os bytes em base64, com o content-type do CDN preservado; thumb que não baixa (rede, HTTP 4xx, grande demais) fica fora da chamada e é avisada no log, e sem nenhuma thumb a chamada nem sai; teto de imagens por chamada equilibrado entre todos os pools, orçamento de tokens que cresce com o nº de imagens, `enable_thinking: false` no pedido e repetição sem o campo quando o gateway devolve 400, parse de âncora → `pos_*` e de `subject` (incluindo `food` e sinônimos como `smoothie`/`fruit`), `<think>`/cerca markdown na resposta, JSON vindo em `reasoning_content` com `content` vazio, `content` devolvido como lista de partes, recuperação dos veredictos inteiros de uma resposta cortada no limite de tokens (inclusive com `}` dentro de string), nota fora de faixa, `image_id` alucinado ou duplicado, gradiente mock sem chamada, timeout e 404 caindo no ranking textual, e resposta inútil registrada no log com `finish_reason` e o conteúdo.
- **Busca em três pools** — queries distintas para pessoa, comida e cenário, cada foto marcada com sua origem, fotos repetidas entre os pools deduplicadas, falha de uma busca não derruba a geração.
- **Settings** — mock vs LLM configurado, compatibilidade reversa, visão desligada por default e herança das credenciais `LLM_*`, `HOOK_*`/`SCENE_QUERY_HINTS` customizáveis.
- **Forms** — validação de `raw_text` (mín 20 chars) só no modo automático, mínimo de 2 blocos no modo roteiro, `theme`, `style`, `slides_count`, parse de `text_positions`, `box_positions` e `box_scales` (inclui valores inválidos e escalas fora dos limites), POST legado sem o campo de modo continua válido.
- **Visão** — timeout próprio (não o HTTP da busca de imagens), default com folga acima dele, e fallback silencioso em timeout/404/JSON ilegível.
- **Rotas** — fluxo completo (`/` → `/create` → `/generate` → `/preview` → `/edit` → `/export` ZIP/PNG/MD), round-trip da posição arrastada até o PNG, ordem dos blocos preservada da submissão à prévia, e `POST /script/split`.

---

## 🔌 Endpoints

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/` | Landing page + status |
| GET | `/goviral` | Gerador de hooks/scripts e importação opcional do painel |
| POST | `/goviral/generate-content` | Gera painel estruturado a partir de briefing (JSON) |
| POST | `/goviral` | Gera o carrossel a partir do painel (nº de imagens vem do painel) |
| POST | `/goviral/parse` | Prévia da distribuição: o que o parser entendeu do painel (JSON) |
| POST | `/goviral/enhance` | Opcional: melhora hook e parágrafos via LLM e acrescenta o script promo do GoViral app — devolve o painel remontado (JSON) |
| GET | `/goviral-assets/<nome>` | Serve os prints do GoViral app usados no slide de fecho |
| GET | `/create` | Formulário de briefing (roteiro por imagem ou texto corrido) |
| POST | `/script/split` | Divide um roteiro colado em blocos por imagem (JSON) |
| POST | `/generate` | Executa composição do carrossel |
| POST | `/rank` | Reordena imagens (JSON) |
| POST | `/pin-person` | Fixa a pessoa da foto do hook (guarda o pin para os próximos carrosséis) |
| POST | `/pin-person/clear` | Esquece a pessoa fixada |
| GET | `/preview/<id>` | Exibe carrossel com slides editáveis |
| POST | `/preview/<id>/edit` | Atualiza slides editados |
| POST | `/preview/<id>/export` | Baixa ZIP / PNG / Markdown |
| GET | `/health` | Health check JSON |

---

## 🎨 Estilos visuais

Cada estilo produz um layout distinto no PNG renderizado:

| Estilo | Layout | Caso de uso |
|--------|--------|-------------|
| `sticker` | **(padrão)** Uma caixa branca arredondada por **linha**, do tamanho daquela linha, texto preto, foto sem escurecimento. As caixas se sobrepõem e a pilha lê como uma mancha contínua. Com 2+ caixas o slide sai **espalhado**: a primeira abre no topo da foto e a última fecha no pé. O texto corre até perto da margem antes de quebrar. Um tamanho de fonte só para headline/corpo/CTA; cada bloco arrasta e redimensiona sozinho na prévia | Photo post nativo do TikTok |
| `sticker_outline` | Mesma geometria do sticker (espalhamento incluso), tinta diferente: texto **branco com contorno preto** de 12% do corpo, sem caixa, tudo num peso só (SemiBold) — o "black outline" do TikTok | Photo post nativo, foto clara demais para caixa branca |
| `quote` | Aspas decorativas + headline centralizada + body + CTA inferior | Frases inspiradoras, quotes |
| `list` | Headline à esquerda com barra de destaque + bullets + CTA centralizado | Listas de dicas, passos numerados |
| `tutorial` | Tag "PASSO A PASSO" + headline + body + CTA em caixa colorida | Tutoriais, como-fazer |
| `story` | Tag "HISTÓRIA" + headline grande + body centralizado + CTA | Narrativas, storytelling |

**Dimensões:** 1080×1350px (4:5) — formato ideal para TikTok photo posts e Instagram Reels cover.

### Tipografia

O projeto **empacota TikTok Sans** em `static/fonts/` — a tipografia oficial do TikTok:

| Arquivo | Corte | Usado em |
|---------|-------|----------|
| `static/fonts/sticker-bold.ttf` | TikTok Sans **SemiBold** (wght 600) | headline e CTA |
| `static/fonts/sticker-regular.ttf` | TikTok Sans **Medium** (wght 500) | corpo do texto |

SemiBold/Medium em vez de Bold/Regular porque o texto nativo do TikTok é de peso médio — Bold fica pesado demais dentro da caixa branca e Regular fica fino demais sobre a foto.

O Google Fonts publica TikTok Sans **apenas como fonte variável**, com default **Light 300**. Os arquivos aqui são instâncias estáticas geradas com `fontTools` — soltar o `.ttf` variável cru renderizaria os slides finos demais, sem erro nenhum. O processo está documentado em [static/fonts/README.md](static/fonts/README.md).

A detecção segue esta ordem: `static/fonts/` → Liberation/DejaVu (Linux) → Segoe UI/Arial (Windows) → Arial (macOS). Ou seja, os arquivos empacotados vencem as fontes do sistema em qualquer ambiente — o render fica igual no Docker e no dev local.

Para trocar a tipografia, substitua esses dois `.ttf` (estáticos) ou aponte `SLIDE_FONT_BOLD` / `SLIDE_FONT_REGULAR` para outros caminhos.

> TikTok Sans é distribuída sob SIL Open Font License 1.1 (`static/fonts/OFL.txt`), copyright 2024 TikTok Inc.

> **Nota:** emoji é removido do PNG (as fontes do sistema não têm esses glifos e o Pillow desenharia um retângulo vazio). O emoji continua na legenda e no Markdown exportado.

---

## 🔐 Segurança
- Tokens são lidos do ambiente e usados apenas no backend.
- CSRF habilitado em todos os forms (Flask-WTF).
- Logs não contêm credenciais.
- Atribuição e link da imagem são exibidos na prévia e no Markdown exportado.
- O `health` endpoint **não** expõe tokens, prompts ou segredos.
- O goviral.ai é acessado manualmente pelo usuário quando ele opta por importar um painel — o ViralPost Studio nunca faz scraping ou automação de login. A geração principal usa o LLM configurado no própriimitações e compliance

- **goviral.ai:** ferramenta externa sem API/token. A importação de um painel é opcional; o gerador principal não depende dele. Quando usado, o usuário acessa via login Discord e cola o texto no formulário. O ViralPost Studio não automatiza o acesso.
- **Pinterest sem token (`IMAGE_PROVIDER=pinterest_scrape` — e a metade Pinterest dos combinados `instagram_pinterest` e `unsplash_pinterest`):** usa a biblioteca [pinterest-dl](https://github.com/sean1832/pinterest-dl), que lê a API **interna** do site. Três consequências que valem a leitura antes de ligar:
  1. **Termos de uso.** Acesso automatizado pode conflitar com os [Terms of Service do Pinterest](https://developers.pinterest.com/terms/). A biblioteca declara uso educacional e não é afiliada ao Pinterest. Ligar a opção é decisão de quem publica — por isso ela nunca entra sozinha no modo `auto`.
  2. **Contrato instável.** Uma API interna muda sem aviso e sem versionamento. Quando mudar, a busca falha e o carrossel cai no gradiente mock com o motivo no aviso da prévia — não quebra a aplicação, mas para de trazer fotos.
  3. **Direitos da imagem.** Um pin não é banco de imagens: a foto costuma ser de terceiros e o Pinterest é só o índice. O link do pin vai na atribuição, mas verifique a origem antes de publicar comercialmente.
- **Instagram sem token (`IMAGE_PROVIDER=instagram_scrape` e `instagram_pinterest`):** lê os endpoints web **anônimos** do próprio site (os mesmos do [instagram-php-scraper](https://github.com/postaddictme/instagram-php-scraper)), sem login e sem credencial. As três ressalvas acima valem inteiras — termos de uso ([Instagram Platform Policy](https://developers.facebook.com/terms/)), contrato instável e direitos da imagem (a foto é de quem postou; o link do post vai na atribuição). Duas particularidades: a busca anônima **por hashtag deixou de existir** — medido em 2026-08-16, o `/api/v1/tags/web_info/` responde `302 → /accounts/login/` em toda saída testada (datacenter, IP residencial doméstico e exits residenciais do ScrapeOps), com e sem bootstrap de cookie, e o HTML de `/explore/tags/<tag>/` não traz mais os posts embutidos. Isso é gate de **endpoint**, não de IP: trocar o IP de saída não passa por ele (foi por isso que o `INSTAGRAM_PROXY` saiu na v0.14), e nos testes imitar o TLS do Chrome (Scrapling) também não muda a resposta. Restam dois caminhos pagos, cada um com termos e custos **de terceiros** que são de quem publica: `APIFY_TOKEN` roda um actor da [Apify](https://apify.com) que raspa com sessão própria (o único com chance na hashtag; cobrança por resultado) e `SCRAPEDO_TOKEN` faz as chamadas da API web saírem pelo gateway do [Scrape.do](https://scrape.do) (serve ao `429` do caminho `@perfil`, que **é** por IP). Sem nenhum dos dois, prefira `pinterest_scrape` — ou `instagram_pinterest`, onde o Pinterest preenche o carrossel quando o Instagram cai, em vez de o slide virar gradiente. Automatizar login segue fora do escopo, pela mesma regra que vale para o goviral.ai. A segunda particularidade: as URLs do CDN (`scontent.cdninstagram.com`) são **assinadas e expiram** — servem para a prévia e o render da sessão, não para guardar. Também nunca entra sozinho no `auto`; a escolha na UI (seletor "Fonte das fotos") ou no `.env` é o opt-in.
- **Unsplash:** gratuito e sem aprovação, com atribuição obrigatória — preservada na prévia e no Markdown exportado.
- **LLM:** o endpoint é opcional. Groq, OpenAI ou qualquer provedor OpenAI-compatible podem ser usados. "Free model" não implica em disponibilidade permanente ou autorização comercial — valide os termos.
- **Persistência:** em memória por processo. Reiniciar o container apaga projetos. Para multi-worker, substitua `SessionStore` por Redis ou DB.
- **Sem automação de conta:** nenhuma parte do código faz login, publica, curte ou segue em Pinterest, goviral.ai, Discord ou TikTok. A única leitura automatizada é a busca pública de pins descrita acima, quando explicitamente habilitada; a geração de texto usa apenas o endpoint LLM configurado pelo usuário.

---

## 🎯 Critérios de aceitação atendidos

- [x] `docker compose up --build` inicia a aplicação.
- [x] `.env.example` documenta todas as configurações.
- [x] Aplicação funciona em modo mock sem credenciais.
- [x] Briefing é validado (raw_text, theme, style, slides_count).
- [x] TextComposer retorna estrutura consistente (slides + hashtags + caption).
- [x] Cliente de imagens é server-side e trata erros.
- [x] LLM pode ser desligado (provider=mock).
- [x] LLM possui fallback funcional (timeout → mock).
- [x] Usuário pode escolher manualmente a imagem de cada slide.
- [x] Roteiro pode ser escrito imagem por imagem, com um campo por foto do carrossel.
- [x] Roteiro colado inteiro é distribuído entre os campos e continua editável.
- [x] Texto colado com `Imagem N:` vai para as fotos indicadas, sem LLM no caminho.
- [x] A imagem 1 mostra o hook sozinho e nunca sai sem texto.
- [x] Cotas ajustáveis distribuem pessoas, comida e cenário — com aviso quando não dá.
- [x] A busca sem token descarta foto que o slide precisaria ampliar.
- [x] Prévia é editável (headline + body + CTA por slide).
- [x] Posição e tamanho de cada caixa são ajustáveis na prévia e o PNG exportado respeita o ajuste.
- [x] Usuário consegue copiar legenda/hashtags e baixar conteúdo.
- [x] Origem da imagem aparece na interface e no Markdown exportado.
- [x] Nenhum segredo aparece no frontend, logs ou repositório.
- [x] Testes unitários para validação, adapters e fallback.
- [x] README com instalação, configuração e execução.
- [x] Não há automação de login nem publicação automática; a busca sem token é opt-in e documentada.

---

## 🛣️ Próximos passos

1. Configurar `VISION_API_KEY` + `VISION_MODEL` na ModelScope (Qwen-VL) para o casting decidir por visão em vez de busca/metadado. É a única peça pendente das features desta versão — o resto já funciona sem chave.
2. Configurar `LLM_API_BASE_URL` e `LLM_API_KEY` (ex.: Groq) para ativar o roteiro viral com LLM real. Modelos Groq suportados: `qwen/qwen3.6-27b`, `llama-3.3-70b-versatile`, `llama-3.1-8b-instant`, `mixtral-8x7b-32768`, `gemma2-9b-it` (consulte https://console.groq.com/docs/models para a lista atual).
4. Adicionar mais estilos visuais (antes-e-depois, capa de carrossel, etc.).
4. Persistência real (DB ou Redis) para multi-worker.
5. Mover a chamada de visão para fora do `POST /generate` (fila ou refinamento sob demanda na prévia), tirando a latência do VLM do caminho da primeira renderização.

---

## 📄 Licença

Uso interno. Componentes externos sujeitos aos seus próprios termos (Pinterest API ToS, goviral.ai, modelo de LLM escolhido).
