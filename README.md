# ViralPost Studio

Aplicação Flask que transforma o texto gerado pelo **goviral.ai** em um carrossel visual pronto para publicar — combinando o texto colado com fotos do Pinterest ou do Instagram (busca **sem token**) ou do Unsplash, composição opcional via LLM e renderização estilo **TikTok photo post** (1080×1350, 4:5).

> **Status:** MVP v0.9 — Ready for building
> **Stack:** Python 3.11 · Flask 3 · Jinja2 · WTForms · Pillow · Docker
> **Idioma inicial:** Português (pt-BR)

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

| Ordem de preferência | Quando entra |
| --- | --- |
| Retrato **e** cobre 1080×1350 | Sempre que o tema tiver acervo para isso. |
| Cobre 1080×1350, em qualquer orientação | Foto grande deitada perde metade da cena no recorte; foto pequena estraga a foto inteira. Entre as duas, a grande. |
| Retrato, em qualquer resolução | Tema sem acervo em alta. |
| O pool inteiro | Último recurso — foto pequena ainda é melhor que gradiente, e ela aparece na galeria da prévia para você trocar. |

Pin sem resolução no payload **não** passa o piso: o pool tem 40 pins e sobra material para exigir prova em vez de dar o benefício da dúvida.

O piso é o próprio tamanho do slide (`SLIDE_WIDTH`×`SLIDE_HEIGHT`) — não há variável nova para configurar. O filtro é feito no pool já recebido, e não no parâmetro `min_resolution` da `pinterest-dl`: lá o corte acontece antes da contagem, então a biblioteca **pagina de novo** para fechar os 40 pins, com um `sleep` por página dentro do `POST /generate`. A busca continua sendo uma requisição só. No Unsplash o problema não existe: a `urls.regular` sai com 1080px de largura e a busca já pede `orientation=portrait`.

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

Não há chave, cota nem conta. Cada busca é **uma requisição**: a API interna devolve 50 pins de uma vez e o cliente recorta o que precisa dessa mesma resposta — pedir mais dispararia uma segunda página com um `sleep` no meio, dentro do `POST /generate`.

Do pool de 40 pins, o recorte aplica três correções — duas delas pelos mesmos motivos que já valiam para o Unsplash:

| Correção | Por quê |
| --- | --- |
| **Resolução primeiro** | O slide tem 1080×1350 e o render faz `cover`: uma foto menor é ampliada e chega ao feed borrada, com a legenda nítida por cima. Ver [Só foto que cobre o slide](#só-foto-que-cobre-o-slide). |
| **Retrato primeiro** | O slide é 4:5. Uma foto deitada perde metade da cena no recorte de cover. O Unsplash resolve com `orientation=portrait`; a API interna não tem esse parâmetro, então o filtro é feito aqui, pela resolução que vem em cada pin. Sem retrato suficiente, o pool inteiro vale — foto deitada ainda é melhor que gradiente. |
| **Ponto de corte sorteado** | A busca vem ordenada por relevância e essa ordem é estável: sem sortear onde o recorte começa, o mesmo tema devolveria as mesmas fotos toda vez. É o mesmo sintoma que parecia cache no Unsplash e era determinismo da API. |

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

### Casting: hook com pessoa, resto com cenário

O problema: uma busca por `"rotina matinal"` devolve xícara, caderno e janela na primeira página — quase nunca o retrato que um hook precisa. Ranquear melhor não resolve, porque a foto de pessoa simplesmente não está no resultado.

A solução tem três camadas, cada uma cobrindo a falha da anterior:

| Camada | Sinal | Vale quando |
| --- | --- | --- |
| **1. Busca em dois pools** | A query roda duas vezes: `"<tema> woman portrait lifestyle aesthetic"` e `"<tema> aesthetic lifestyle travel food"`. Cada foto lembra de qual pool veio. | Sempre — é o que garante que existe foto de pessoa no conjunto. |
| **2. Metadado** | Palavras no título/descrição (`woman`, `girl`, `portrait`, `mulher`…). O Unsplash descreve as fotos como "a woman sitting on a bed". | Sem VLM configurado. |
| **3. Visão** | O VLM olha a foto e classifica o assunto. Vence as outras duas: a busca de retrato às vezes devolve paisagem, e o metadado às vezes está vazio. | `VISION_ENABLED=true`. |

O resultado é gravado como `image_id` em cada slide — o mesmo campo que a galeria da prévia edita. Ou seja: o casting é um **palpite inicial**, não uma trava. Discordou? Troque a foto na prévia com um clique.

Se nenhuma foto de pessoa aparecer em nenhuma das camadas, o slide de hook fica com a foto melhor ranqueada e um aviso amarelo aparece na prévia — o app diz o que não conseguiu em vez de fingir que deu certo.

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

## 🔌 Sobre o goviral.ai

O `content.goviralai.app` **não possui API pública** — responde `HTTP 403` a qualquer requisição programática e não publica documentação de desenvolvedor. A autenticação é uma sessão Discord presa ao navegador.

Reaproveitar essa sessão no servidor significaria repassar seus cookies, ou seja, automação de login não autorizada — exatamente o que o escopo deste projeto proíbe e o que pode derrubar sua conta. Por isso o fluxo continua sendo **colar o texto**, e o trabalho de estruturação acontece aqui, via Groq.

---

## ✨ Funcionalidades do MVP

- Landing page com link direto para o goviral.ai (login Discord manual).
- **Tela "Colar do painel" (`/goviral`)** — o dashboard do goviral colado inteiro vira o carrossel: hook + um script por imagem, nº de imagens decidido pelo painel, prévia da distribuição antes de gerar.
- Formulário com **um campo de roteiro por imagem** (rotulado pelo papel do slide) ou textarea única, mais tema, estilo, nº de slides, idioma e keywords.
- **Rótulo `Imagem N:` no texto colado dispensa o LLM** — vale nas duas caixas de texto; a linha em branco dentro do trecho separa as duas caixas da imagem. O **painel do goviral** (Hook + Script + Paragraph) é reconhecido do mesmo jeito, sem rótulo nenhum.
- Botão "distribuir" que divide um roteiro colado entre os campos, entendendo `Imagem N:` (com nota entre parênteses ou sozinho na linha), `2.`, `---`, o intervalo de duas linhas em branco e parágrafos.
- **Casting por papel**: imagem 1 sempre com pessoa (hook), demais com cenário — via busca separada, metadado da foto e visão.
- Composição de carrossel via TextComposer (mock determinístico ou LLM); no modo por imagem — e em qualquer texto colado com rótulos —, sem LLM no caminho do texto.
- **Imagem 1 sempre com o hook sozinho, e nunca em branco** — uma caixa, sem texto de apoio e sem CTA, nos três caminhos de composição.
- Ordenação no roteiro viral de 3 atos (`hook → problema → agitação → valor → prova → CTA`).
- Renderização estilo sticker do TikTok — caixas brancas arredondadas com texto preto.
- Busca de imagens via Pinterest **sem token** (`pinterest-dl`), via **Instagram sem token** (hashtag ou @perfil), via Unsplash ou mock — combinável (Instagram + Pinterest intercalados) e escolhível **por geração** no seletor "Fonte das fotos" dos formulários.
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

1. Acesse [https://content.goviralai.app/](https://content.goviralai.app/) (login Discord) **em outra aba**.
2. Gere o texto pronto lá.
3. No ViralPost Studio (`http://localhost:5000/create`), escolha o nº de slides (3/6/9/12) e como entregar o texto:
   - **Roteiro por imagem** (padrão) — um campo por foto, rotulado com o papel do slide: *Imagem 1 (hook)*, *Imagem 2 (problema)*, e assim por diante. Dentro de um campo, pule uma linha para mandar o texto seguinte para a outra caixa daquela imagem; sem linha em branco, a primeira linha vira o texto grande e o resto vira o apoio — menos na **imagem 1**, que sai como uma frase só (o hook, sem apoio e sem CTA). Nada de LLM no meio: o que você escreve é o que sai.
   - **Distribuir de uma vez** — dentro do modo por imagem, abra "Colar o roteiro inteiro e distribuir", cole tudo e clique no botão. O servidor divide por `Imagem N:`, `2.`, `---`, intervalo de duas linhas em branco ou parágrafos e preenche os campos, que continuam editáveis.
   - **Texto corrido** — cole tudo numa caixa só e deixe o LLM estruturar. Se você escrever `Imagem 1:`, `Imagem 2:`… na frente dos trechos, o LLM **não entra**: cada trecho vai para a foto que você indicou (ver [O rótulo diz a imagem, a linha em branco diz a caixa](#o-rótulo-diz-a-imagem-a-linha-em-branco-diz-a-caixa)).
4. Preencha tema, estilo (**sticker** recomendado — ou quote/list/tutorial/story) e as palavras-chave da busca de imagens.
5. Clique em "Gerar carrossel". Com o casting ligado, a imagem 1 recebe uma foto com pessoa e as demais recebem cenário.
6. Na prévia, cada slide mostra seu papel e de onde veio a foto do hook (visão, metadado ou busca). Edite os textos e troque a imagem pela galeria.
7. No estilo `sticker`, **arraste cada caixa** sobre a foto para reposicionar (duplo clique volta ao padrão) e use o controle de tamanho de cada caixa se quiser texto maior. Clique em "Salvar edições" para gravar.
8. Exporte: **ZIP** (carrossel completo) ou **PNG** (slide único) ou **Markdown** (texto).

---

## ⚙️ Variáveis de ambiente

| Variável | Default | Descrição |
|----------|---------|-----------|
| `FLASK_ENV` | `development` | Ambiente Flask |
| `SECRET_KEY` | `dev-insecure-change-me` | **Definir em produção** |
| `DEBUG` | `true` | Modo debug |
| `IMAGE_PROVIDER` | `auto` | De onde vêm as fotos: `auto`, `pinterest_scrape`, `unsplash`, `instagram_scrape`, `instagram_pinterest` ou `mock`. O seletor "Fonte das fotos" dos formulários vence este valor por geração |
| `UNSPLASH_ACCESS_KEY` | (vazio) | Access Key do Unsplash — a **única** fonte de imagens com chave. Vazio (com `auto`) → mock |
| `APIFY_TOKEN` | (vazio) | Token da [Apify](https://apify.com): roda um **actor** que raspa o Instagram com sessão própria e devolve dataset estruturado. É o único transporte com chance na busca por hashtag, e **vence** o `SCRAPEDO_TOKEN` quando os dois existem |
| `APIFY_ACTOR` | `apify~instagram-scraper` | Qual actor rodar (id com **til** no lugar da barra). Cobre hashtag e `@perfil` |
| `SCRAPEDO_TOKEN` | (vazio) | Token do [Scrape.do](https://scrape.do): as mesmas chamadas da API web saem pelo gateway deles (proxies residenciais, `super=true`, 10x créditos). **Não** vence o muro da hashtag — é gate de endpoint; serve ao `429` do caminho `@perfil` |
| `LLM_PROVIDER` | `mock` | `mock` ou `openai_compatible` |
| `LLM_API_BASE_URL` | (vazio) | Endpoint OpenAI-compatible (ex.: `https://api.groq.com/openai/v1`) |
| `LLM_API_KEY` | (vazio) | Token do LLM (ex.: `gsk_...` para Groq) |
| `LLM_MODEL` | (vazio) | Nome do modelo. Ex.: `qwen/qwen3.6-27b`, `llama-3.3-70b-versatile`, `gpt-4o-mini` |
| `RANKING_ENABLED` | `true` | Liga/desliga ranking de imagens (reusa LLM) |
| `HOOK_SUBJECT` | `woman` | Casting da imagem 1: `woman`, `person` ou `off` (desliga o casting) |
| `HOOK_QUERY_HINTS` | (auto) | Termos da busca de retrato. Vazio → `<HOOK_SUBJECT> portrait lifestyle aesthetic` |
| `SCENE_QUERY_HINTS` | `aesthetic lifestyle travel food` | Termos da busca das imagens secundárias |
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

**Por que a mesma query devolve fotos diferentes agora:** o `/search/photos` do Unsplash ordena por relevância e essa ordem é estável — a página 1 de "café da manhã" é sempre a mesma. Não havia cache no app; era determinismo da API. Cada busca agora sorteia uma página entre 1 e 5 (`UnsplashClient._PAGE_WINDOW`), o que renova o resultado sem cair em fotos irrelevantes. A página escolhida aparece no log `INFO`. Se a query tem acervo curto e a página sorteada vem vazia, a busca reentra dentro do `total_pages` em vez de cair no gradiente mock.

Para confirmar o que está ativo:

```bash
curl -s http://localhost:5000/health | python -m json.tool
# providers.images        → "pinterest_scrape" | "unsplash" | "instagram_scrape" | "mock"
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
│   │   ├── casting.py         # Qual foto em qual slide (hook = pessoa)
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

Cobertura (414 testes):
- **Pessoa fixada** — round-trip de gravar/ler/esquecer em `instance/pinned_person.json`; URL do pin canonizada (domínio regional e sufixos viram `www.pinterest.com/pin/<id>/`); foto que não é pin (Unsplash, mock, goviral_assets) não é fixável e a rota explica com 422; `related()` do cliente de scrape mapeia os pins para a forma do app, aplica o piso de resolução e devolve `[]` em falha (sem mock — quem chama tem fallback melhor); com o checkbox ligado o pool de hook vem dos relacionados (uma query só, a de cenário) e o slide 1 recebe uma foto deles; ninguém fixado, provider sem `related`, relacionados vazios/erro e casting desligado caem na busca de sempre com o motivo nos avisos; com o checkbox desligado nada muda; o formulário carrega o checkbox até o serviço.
- **Painel do goviral** — o dashboard colado com `Ctrl+A` vira um bloco por imagem (hook numa linha só, parágrafos nas duas caixas); preâmbulo antes do `Hook` descartado sem lista de interface; rótulos nunca chegam ao slide; texto na mesma linha do rótulo ou na seguinte; rótulos das duas colunas antes dos dois textos; `Position` decidindo a ordem; painel sem cabeçalho `Script` dividido pelo `Paragraph 1`; parágrafo multi-linha na mesma caixa; `Paragraph 3` na caixa de baixo; reconhecido pela metade (sem `Hook`, sem texto, só scripts) responde "não é painel"; `Imagem N:` continua sendo do `labeled_blocks`; e as rotas — `/goviral` gera sem perguntar nº de slides, 422 com motivo quando não é painel, `/goviral/parse` mostra a distribuição, o "distribuir" do briefing entende o painel e o painel na caixa única pula o composer.
- **TextComposer** — split em slides, hashtags, texto curto, texto vazio, e as linhas em branco do texto colado sobrevivendo à limpeza das hashtags (colapsá-las fazia todos os slides saírem com o roteiro inteiro).
- **Rótulo `Imagem N`** — nota entre parênteses e rótulo sozinho na linha continuam sendo rótulo; hora no começo da linha (`5:30 da manhã`) não é rótulo; `labeled_blocks` só responde quando os rótulos existem; rótulo digitado dentro do campo não chega ao slide; texto colado com rótulos pula o composer, mantém a ordem e avisa quantos rótulos foram obedecidos, e texto sem rótulo continua indo para o composer.
- **Caixa vs. imagem** — linha em branco dentro do bloco separa as duas caixas daquela imagem, duas linhas em branco separam as imagens, uma caixa de duas linhas sai como uma frase, e no bloco da imagem 1 a linha em branco não cria segunda caixa.
- **Roteiro por imagem** — primeira linha vira headline e o resto o body, rótulos `Imagem N:` removidos, campo vazio herda o papel, blocos além do nº de slides descartados, hashtags e CTA preservados.
- **A imagem 1 é uma caixa só** — o bloco de duas linhas vira uma frase (sem virar headline + apoio) e o hook não é cortado no limite de headline, no roteiro manual **e** no caminho LLM (onde o corte de 70 vinha antes de o slide ser reconhecido como hook); o composer mock devolve o hook sem body nem CTA, com o primeiro trecho e nada mais, e mantém as duas caixas nos outros slides; no LLM o body e o CTA do slide 1 são apagados mesmo quando o modelo os escreve **sem colar o apoio na frase** (a frase mandada no lugar da headline ainda vira o hook), o papel do slide 1 é `hook` independente do que o modelo rotule, e o slide 1 nunca sai sem texto nas quatro formas de o modelo desobedecer ao prompt; a prévia entrega os campos de apoio e CTA da imagem 1 em leitura apenas e a gravação limpa os dois; um hook longo continua validando no formulário de edição.
- **Distribuição do roteiro colado** — separadores `Imagem N:`, `2.`, `---` e parágrafo; teto no nº de slides com o total encontrado reportado; texto vazio e contagem inválida.
- **Casting** — hook recebe pessoa por visão, por metadado (`alt_description`) e por pool de busca, nessa ordem; parte do corpo ("woman's hands") não conta como retrato; fotos de cenário nunca caem no slide 1; aviso quando não há foto com pessoa; `HOOK_SUBJECT=off` volta à rotação.
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
- **Piso de resolução** — pin menor que o slide fica de fora; foto grande deitada vence foto pequena em pé; sem acervo em alta o piso cai em vez de o carrossel virar gradiente; pin sem resolução não passa o piso; o piso vem de `SLIDE_WIDTH`×`SLIDE_HEIGHT`; e o `min_resolution` da biblioteca continua em `(0, 0)`, para a busca não paginar dentro do `POST /generate`.
- **Escolha do provider** — `IMAGE_PROVIDER` default `auto` e valor desconhecido caindo em `auto` (inclusive o `pinterest_v5` removido); o scraping só entra quando escolhido, nunca no `auto`; `auto` prefere Unsplash e cai no mock sem chave; `mock` ignora a chave configurada; escolha impossível (Unsplash sem chave) desce a escada em vez de devolver um cliente quebrado; e um `PINTEREST_ACCESS_TOKEN` sobrando no ambiente não vira cliente nem desvia a escada.
- **Prompt do roteiro** — a regra do hook sozinho e a ordem dos papéis chegam no prompt, e o orçamento de tokens cresce com o nº de slides (o teto fixo cortava o JSON de 12 slides).
- **Unsplash** — rotação de páginas entre buscas iguais, reentrada quando a página sorteada passa do fim do acervo, motivo do fallback por status HTTP.
- **Ranking** — correlação com `raw_text`, fallback sem corpus.
- **Visão (VLM)** — baixa a thumb (não a foto cheia) e manda os bytes em base64, com o content-type do CDN preservado; thumb que não baixa (rede, HTTP 4xx, grande demais) fica fora da chamada e é avisada no log, e sem nenhuma thumb a chamada nem sai; teto de imagens por chamada equilibrado entre os dois pools, orçamento de tokens que cresce com o nº de imagens, `enable_thinking: false` no pedido e repetição sem o campo quando o gateway devolve 400, parse de âncora → `pos_*` e de `subject` (com sinônimos: `female`/`girl` → `woman`), `<think>`/cerca markdown na resposta, JSON vindo em `reasoning_content` com `content` vazio, `content` devolvido como lista de partes, recuperação dos veredictos inteiros de uma resposta cortada no limite de tokens (inclusive com `}` dentro de string), nota fora de faixa, `image_id` alucinado ou duplicado, gradiente mock sem chamada, timeout e 404 caindo no ranking textual, e resposta inútil registrada no log com `finish_reason` e o conteúdo.
- **Busca em dois pools** — uma query por papel, cada foto marcada com sua origem, fotos repetidas entre os pools deduplicadas, falha de uma busca não derruba a geração.
- **Settings** — mock vs LLM configurado, compatibilidade reversa, visão desligada por default e herança das credenciais `LLM_*`, `HOOK_*`/`SCENE_QUERY_HINTS` customizáveis.
- **Forms** — validação de `raw_text` (mín 20 chars) só no modo automático, mínimo de 2 blocos no modo roteiro, `theme`, `style`, `slides_count`, parse de `text_positions`, `box_positions` e `box_scales` (inclui valores inválidos e escalas fora dos limites), POST legado sem o campo de modo continua válido.
- **Visão** — timeout próprio (não o HTTP da busca de imagens), default com folga acima dele, e fallback silencioso em timeout/404/JSON ilegível.
- **Rotas** — fluxo completo (`/` → `/create` → `/generate` → `/preview` → `/edit` → `/export` ZIP/PNG/MD), round-trip da posição arrastada até o PNG, ordem dos blocos preservada da submissão à prévia, e `POST /script/split`.

---

## 🔌 Endpoints

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/` | Landing page + status |
| GET | `/goviral` | Colar o painel do goviral inteiro — hook + scripts viram as imagens |
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
- O goviral.ai é acessado manualmente pelo usuário — o ViralPost Studio nunca faz scraping ou automação de login.

---

## ⚠️ Limitações e compliance

- **goviral.ai:** ferramenta externa sem API/token. O usuário é responsável por acessar via login Discord e colar o texto no formulário. O ViralPost Studio não automatiza o acesso.
- **Pinterest sem token (`IMAGE_PROVIDER=pinterest_scrape`):** usa a biblioteca [pinterest-dl](https://github.com/sean1832/pinterest-dl), que lê a API **interna** do site. Três consequências que valem a leitura antes de ligar:
  1. **Termos de uso.** Acesso automatizado pode conflitar com os [Terms of Service do Pinterest](https://developers.pinterest.com/terms/). A biblioteca declara uso educacional e não é afiliada ao Pinterest. Ligar a opção é decisão de quem publica — por isso ela nunca entra sozinha no modo `auto`.
  2. **Contrato instável.** Uma API interna muda sem aviso e sem versionamento. Quando mudar, a busca falha e o carrossel cai no gradiente mock com o motivo no aviso da prévia — não quebra a aplicação, mas para de trazer fotos.
  3. **Direitos da imagem.** Um pin não é banco de imagens: a foto costuma ser de terceiros e o Pinterest é só o índice. O link do pin vai na atribuição, mas verifique a origem antes de publicar comercialmente.
- **Instagram sem token (`IMAGE_PROVIDER=instagram_scrape` e `instagram_pinterest`):** lê os endpoints web **anônimos** do próprio site (os mesmos do [instagram-php-scraper](https://github.com/postaddictme/instagram-php-scraper)), sem login e sem credencial. As três ressalvas acima valem inteiras — termos de uso ([Instagram Platform Policy](https://developers.facebook.com/terms/)), contrato instável e direitos da imagem (a foto é de quem postou; o link do post vai na atribuição). Duas particularidades: a busca anônima **por hashtag deixou de existir** — medido em 2026-08-16, o `/api/v1/tags/web_info/` responde `302 → /accounts/login/` em toda saída testada (datacenter, IP residencial doméstico e exits residenciais do ScrapeOps), com e sem bootstrap de cookie, e o HTML de `/explore/tags/<tag>/` não traz mais os posts embutidos. Isso é gate de **endpoint**, não de IP: trocar o IP de saída não passa por ele (foi por isso que o `INSTAGRAM_PROXY` saiu na v0.14), e nos testes imitar o TLS do Chrome (Scrapling) também não muda a resposta. Restam dois caminhos pagos, cada um com termos e custos **de terceiros** que são de quem publica: `APIFY_TOKEN` roda um actor da [Apify](https://apify.com) que raspa com sessão própria (o único com chance na hashtag; cobrança por resultado) e `SCRAPEDO_TOKEN` faz as chamadas da API web saírem pelo gateway do [Scrape.do](https://scrape.do) (serve ao `429` do caminho `@perfil`, que **é** por IP). Sem nenhum dos dois, prefira `pinterest_scrape` — ou `instagram_pinterest`, onde o Pinterest preenche o carrossel quando o Instagram cai, em vez de o slide virar gradiente. Automatizar login segue fora do escopo, pela mesma regra que vale para o goviral.ai. A segunda particularidade: as URLs do CDN (`scontent.cdninstagram.com`) são **assinadas e expiram** — servem para a prévia e o render da sessão, não para guardar. Também nunca entra sozinho no `auto`; a escolha na UI (seletor "Fonte das fotos") ou no `.env` é o opt-in.
- **Unsplash:** gratuito e sem aprovação, com atribuição obrigatória — preservada na prévia e no Markdown exportado.
- **LLM:** o endpoint é opcional. Groq, OpenAI ou qualquer provedor OpenAI-compatible podem ser usados. "Free model" não implica em disponibilidade permanente ou autorização comercial — valide os termos.
- **Persistência:** em memória por processo. Reiniciar o container apaga projetos. Para multi-worker, substitua `SessionStore` por Redis ou DB.
- **Sem automação de conta:** nenhuma parte do código faz login, publica, curte ou segue em Pinterest, goviral.ai, Discord ou TikTok. A única leitura automatizada é a busca pública de pins descrita acima, quando explicitamente habilitada.

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
- [x] Primeira foto recebe pessoa; as demais, cenário — com aviso quando não dá.
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
