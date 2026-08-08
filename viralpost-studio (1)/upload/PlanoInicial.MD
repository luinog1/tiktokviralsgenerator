Plano inicial — ViralPost Studio
O que estamos construindo
Um aplicativo que combina textos gerados pelo criador de conteúdo do ViralAI com imagens obtidas pela API oficial do Pinterest, produzindo posts prontos para revisão e publicação em formatos inspirados em redes sociais como TikTok e Pinterest.

O acesso ao ViralAI deve ser feito por uma integração autorizada — por exemplo, OAuth, API oficial ou fluxo de login permitido — e não por scraping de uma conta Discord ou automação que viole os termos do serviço.

Foco atual
Construir o MVP clicável com:

tela de login e conexão das contas;
formulário para informar tema, nicho, tom e formato do post;
geração de texto usando a integração disponível do ViralAI;
busca de imagens pela API oficial do Pinterest usando o token fornecido;
montagem de uma prévia simples com título, legenda e imagem;
opção de copiar o conteúdo ou baixar a prévia.
A publicação automática em TikTok/Pinterest e recursos avançados ficam fora deste primeiro MVP até validarmos as integrações e as permissões das APIs.

Pode criar um PRD para isso em markdown?

Check team status
PRD — ViralPost Studio
Status: Rascunho
Versão: 0.1
Idioma inicial: Português
Produto: Aplicativo de geração de conteúdo para redes sociais

1. Visão geral
O ViralPost Studio será uma aplicação que transforma um tema ou briefing em um post pronto para revisão, combinando:

Texto gerado pelo criador de conteúdo do ViralAI;
Imagens localizadas por meio da API oficial do Pinterest;
Um layout visual simples para prévia;
Opções para copiar o texto e baixar o conteúdo.
O produto será inspirado no tipo de conteúdo visual produzido por criadores de conteúdo em redes sociais, mas não deverá copiar identidade visual, conteúdo ou materiais protegidos de terceiros.

2. Problema
Criadores e pequenos negócios precisam produzir conteúdo com frequência, mas normalmente precisam:

Pesquisar ideias;
Escrever títulos e legendas;
Encontrar imagens adequadas;
Organizar o conteúdo em um formato publicável;
Repetir esse processo para cada postagem.
Esse trabalho é demorado e exige alternar entre várias ferramentas.

3. Objetivo do produto
Permitir que um usuário gere rapidamente uma sugestão de post visual a partir de um briefing simples, com texto e imagem relacionados ao tema.

Objetivos do MVP
Permitir o acesso seguro do usuário;
Solicitar tema, nicho, tom e formato;
Gerar texto usando uma integração autorizada com o ViralAI;
Buscar imagens por meio da API oficial do Pinterest;
Apresentar uma prévia do post;
Permitir copiar o texto;
Permitir baixar a prévia;
Manter o conteúdo editável antes do download.
Fora do escopo do MVP
Publicação automática no TikTok;
Publicação automática no Pinterest;
Agendamento de posts;
Geração de vídeos;
Criação de carrosséis;
Banco de imagens próprio;
Automação por scraping;
Reprodução automática do fluxo de login via Discord;
Copiar ou replicar exatamente o formato de um criador específico.
4. Público-alvo
Persona principal — Criador de conteúdo
Publica regularmente em redes sociais;
Precisa de ideias e textos com rapidez;
Tem pouca disponibilidade para edição;
Quer revisar o conteúdo antes de publicar.
Persona secundária — Pequeno negócio
Precisa divulgar produtos, serviços ou dicas;
Não possui equipe dedicada de marketing;
Busca consistência visual e textual;
Pode utilizar o conteúdo em Instagram, Pinterest, TikTok ou outras plataformas.
Persona futura — Agência ou social media
Produz conteúdo para vários clientes;
Precisa criar múltiplas variações;
Necessita salvar projetos e organizar conteúdos.
5. Proposta de valor
“Crie um post visual pronto para revisar em poucos minutos, usando um único briefing.”

O produto não substitui a revisão humana. Ele acelera a etapa de ideação, redação e composição inicial.

6. Fluxo principal do usuário
6.1 Primeiro acesso
Usuário acessa a aplicação;
Visualiza uma explicação breve do produto;
Faz login ou cria uma conta;
Conecta as integrações disponíveis:
ViralAI;
Pinterest;
É direcionado ao painel de criação.
6.2 Geração de um post
Usuário informa o tema;
Seleciona ou informa:
Nicho;
Público-alvo;
Tom de voz;
Objetivo do post;
Formato;
Idioma;
Clica em Gerar conteúdo;
O sistema solicita ou gera o texto no ViralAI;
O sistema pesquisa imagens relacionadas no Pinterest;
O sistema monta a prévia;
Usuário revisa e edita;
Usuário copia o texto ou baixa a imagem;
Usuário publica manualmente na rede social desejada.
6.3 Falha de integração
Caso uma integração não esteja disponível:

O sistema deve informar claramente o motivo;
Não deve exibir uma geração como concluída quando ela falhou;
Deve oferecer uma ação para tentar novamente;
Deve preservar o briefing preenchido;
Deve evitar expor tokens, cookies ou detalhes técnicos sensíveis.
7. Requisitos funcionais
RF-01 — Cadastro e autenticação
O sistema deve permitir que o usuário:

Crie uma conta;
Faça login;
Encerre a sessão;
Recupere o acesso, caso essa funcionalidade seja implementada pelo provedor de autenticação.
A autenticação do ViralAI não deve depender de scraping, captura de senha ou automação não autorizada do Discord.

RF-02 — Conexão com o ViralAI
O sistema deve permitir conectar o ViralAI por um mecanismo autorizado, conforme o que o serviço disponibilizar:

API oficial;
OAuth;
Token de integração;
Outro mecanismo documentado e permitido.
A implementação deverá ser condicionada à existência de uma API ou método de integração oficialmente permitido.

O sistema deve:

Armazenar credenciais de forma segura;
Nunca mostrar tokens completos na interface;
Permitir desconectar a integração;
Exibir o status da conexão;
Informar quando a credencial estiver inválida ou expirada.
RF-03 — Conexão com o Pinterest
O sistema deve utilizar a API oficial do Pinterest, respeitando:

Escopos autorizados;
Limites de requisições;
Políticas de uso da API;
Direitos de uso das imagens;
Termos de licenciamento e atribuição aplicáveis.
O sistema deve permitir:

Inserir ou conectar uma credencial de forma segura;
Validar a conexão;
Buscar Pins relacionados a uma consulta;
Exibir origem da imagem;
Linkar para o Pin original;
Desconectar a integração.
O token nunca deve ser exposto no navegador, em logs ou no código-fonte público.

RF-04 — Formulário de briefing
O formulário deve conter, no mínimo:

Campo	Obrigatório	Descrição
Tema	Sim	Assunto principal do post
Nicho	Não	Ex.: moda, fitness, culinária
Público-alvo	Não	Para quem o conteúdo é destinado
Tom de voz	Sim	Ex.: educativo, divertido, profissional
Objetivo	Não	Ex.: engajamento, tráfego, vendas
Formato	Sim	Ex.: dica, lista, tutorial, inspiração
Idioma	Sim	Idioma do texto
Palavras-chave	Não	Termos que devem aparecer
O sistema deve validar o tema e impedir o envio de um briefing vazio.

RF-05 — Geração de texto
O sistema deve solicitar ao ViralAI conteúdo estruturado, podendo incluir:

Título;
Texto principal;
Legenda;
Chamada para ação;
Hashtags;
Sugestão de texto alternativo;
Sugestão de título para a imagem.
O resultado deve ser editável pelo usuário.

O sistema deve permitir gerar uma nova variação sem apagar automaticamente a versão anterior, caso o usuário deseje compará-las.

RF-06 — Busca de imagens
A partir do tema e das palavras-chave, o sistema deve:

Gerar uma consulta de busca;
Consultar o Pinterest;
Exibir resultados relevantes;
Permitir selecionar uma imagem;
Mostrar a fonte e o link original.
A aplicação deve deixar claro que encontrar uma imagem no Pinterest não significa automaticamente possuir autorização comercial para reutilizá-la.

RF-07 — Montagem da prévia
A prévia deve incluir:

Imagem selecionada;
Título;
Texto principal ou resumo;
Legenda;
Chamada para ação;
Identificação opcional da fonte;
Layout vertical compatível com redes sociais.
O usuário deve conseguir:

Editar título;
Editar texto;
Editar legenda;
Alterar a imagem;
Gerar outra imagem;
Reorganizar ou ocultar alguns elementos;
Visualizar a versão final antes do download.
RF-08 — Exportação
O MVP deve permitir:

Copiar a legenda;
Copiar hashtags;
Baixar a prévia em PNG ou JPEG;
Baixar o texto em formato simples ou Markdown.
A exportação deve incluir, quando necessário, a atribuição ou o link da imagem de origem.

RF-09 — Histórico básico
Se couber no escopo técnico do MVP, o sistema deve salvar:

Briefing;
Texto gerado;
Imagem selecionada;
Data de criação;
Status da geração.
O usuário deve conseguir abrir novamente um conteúdo gerado e editá-lo.

Caso o armazenamento ultrapasse o escopo do primeiro MVP, o histórico poderá ser substituído temporariamente por uma sessão local no navegador.

8. Requisitos não funcionais
Segurança
Tokens devem ser armazenados no servidor ou em mecanismo seguro de secrets;
Tokens não devem ser enviados ao cliente;
Logs não devem conter credenciais;
Sessões devem possuir expiração;
A aplicação deve usar HTTPS em produção;
Dados de integração devem ser revogáveis pelo usuário.
Privacidade
Informar quais dados são armazenados;
Permitir desconectar integrações;
Evitar armazenar mais dados do que o necessário;
Permitir exclusão do histórico, se o histórico persistente for implementado;
Não usar conteúdo privado do usuário sem consentimento.
Desempenho
Exibir estado de carregamento durante geração e busca;
Permitir cancelamento ou nova tentativa quando possível;
Evitar bloquear a interface durante chamadas externas;
Informar erros de forma compreensível.
Compatibilidade
Desktop e mobile responsivos;
Navegadores modernos;
Prévia vertical adequada para telas móveis.
Acessibilidade
Contraste adequado;
Labels em todos os campos;
Navegação por teclado;
Textos alternativos para imagens;
Mensagens de erro associadas aos campos.
9. Arquitetura conceitual
text
[Interface Web]
       |
       v
[Backend da aplicação]
       |
       +--> [Autenticação]
       |
       +--> [Integração ViralAI]
       |
       +--> [Pinterest API]
       |
       +--> [Gerador de prévia]
       |
       +--> [Banco de dados opcional]
Princípios
As chamadas ao Pinterest devem ocorrer no backend;
A integração com o ViralAI deve usar apenas métodos autorizados;
A aplicação deve abstrair provedores externos para permitir troca futura;
Falhas externas devem ser tratadas sem perder o briefing do usuário.
10. Modelo de dados inicial
User
id
email ou identificador do provedor
created_at
Integration
id
user_id
provider
encrypted_access_token
status
expires_at
created_at
updated_at
ContentProject
id
user_id
theme
niche
audience
tone
objective
format
language
keywords
status
created_at
updated_at
GeneratedContent
id
project_id
title
body
caption
call_to_action
hashtags
alt_text
provider
created_at
SelectedImage
id
project_id
image_url
source_url
source_provider
attribution_text
created_at
11. Telas do MVP
11.1 Landing page
Proposta de valor;
Explicação do fluxo;
Botão de login;
Aviso sobre uso autorizado de APIs e direitos das imagens.
11.2 Login
Login;
Cadastro;
Recuperação de acesso, se suportada.
11.3 Integrações
Status do ViralAI;
Status do Pinterest;
Botões conectar, testar e desconectar;
Aviso de segurança.
11.4 Dashboard
Botão Novo post;
Lista de conteúdos recentes, se houver histórico;
Status das integrações.
11.5 Criador de conteúdo
Formulário de briefing;
Botão de geração;
Mensagens de progresso;
Tratamento de erros.
11.6 Editor e prévia
Canvas ou cartão vertical;
Campos editáveis;
Seleção de imagem;
Botões copiar, baixar e gerar novamente.
12. Critérios de aceitação do MVP
O MVP será considerado funcional quando:

 Um usuário consegue acessar a aplicação;
 O usuário consegue visualizar o status das integrações;
 O usuário consegue preencher um briefing;
 O sistema valida campos obrigatórios;
 O sistema consegue chamar o ViralAI por uma integração autorizada, quando disponível;
 O sistema consegue buscar imagens usando a API oficial do Pinterest;
 Os resultados exibem a origem da imagem;
 O usuário consegue escolher uma imagem;
 O texto e a imagem aparecem em uma prévia;
 O usuário consegue editar o conteúdo;
 O usuário consegue copiar a legenda;
 O usuário consegue baixar a prévia;
 Tokens não aparecem no frontend nem nos logs;
 Erros de integração são exibidos com clareza;
 O sistema não faz scraping ou automação de login não autorizada.
13. Riscos e dependências
Integração com o ViralAI
O maior risco é a inexistência de uma API pública ou de um método autorizado para uso externo. O acesso via Discord pode ser válido para uso humano, mas não necessariamente autoriza automação.

Mitigação: confirmar a documentação, política de uso e método oficial de integração antes de implementar a conexão.

Direitos das imagens
Imagens encontradas no Pinterest podem pertencer a terceiros e não estar licenciadas para reutilização.

Mitigação:

Exibir a fonte original;
Manter atribuição quando aplicável;
Preferir imagens com licença compatível;
Avaliar futuramente integração com bancos de imagens licenciadas;
Exibir aviso de responsabilidade ao usuário.
Limites da API do Pinterest
A API pode limitar consultas, campos disponíveis ou tipos de conteúdo retornados.

Mitigação: implementar paginação, cache controlado, mensagens de limite e tratamento de falhas.

Publicação em redes sociais
A publicação automática dependerá das APIs e permissões de cada plataforma.

Mitigação: manter o MVP focado em geração, revisão e download.

14. Métricas futuras
Após o lançamento do MVP, acompanhar:

Número de usuários que concluem o primeiro briefing;
Tempo médio entre briefing e prévia;
Taxa de geração concluída com sucesso;
Número de prévias baixadas;
Número de conteúdos copiados;
Taxa de retorno dos usuários;
Falhas por integração;
Imagens substituídas antes da exportação.
Essas métricas só devem ser avaliadas depois que houver usuários reais utilizando o produto.

15. Decisões pendentes
Antes da implementação completa, será necessário definir:

O ViralAI possui API oficial ou outro método de integração autorizado?
O acesso será individual por usuário ou haverá uma conta central?
O Pinterest permitirá o tipo de busca e campos necessários para o produto?
O usuário poderá usar qualquer imagem retornada ou apenas imagens com licença selecionada?
O histórico será persistente desde o MVP?
O formato inicial será apenas uma imagem vertical?
Qual será o primeiro canal prioritário: Pinterest, TikTok, Instagram ou uso genérico?
O produto será gratuito, freemium ou pago?
16. Próximo passo recomendado
Validar primeiro as condições técnicas e legais das duas integrações, especialmente a disponibilidade de uma API ou método autorizado do ViralAI. Em seguida, construir o fluxo mínimo:

briefing → geração de texto → busca de imagem → prévia → download.

criar em python e flask, para dockerizar. Se possível utilizar um endpoint de inferência para rankear melhores fotos. Como o groq, free models para isso. Atualizar o PRD e ready for building.

Vou atualizar o PRD para uma arquitetura Flask/Python containerizada, incluir um serviço opcional de ranking de imagens via endpoint de inferência e deixar o escopo executável para construção; primeiro vou preparar um engenheiro full-stack para implementar o MVP.

List capabilities
PRD — ViralPost Studio
Status: Ready for building
Versão: 0.2
Stack: Python, Flask, Jinja2/HTML/CSS/JavaScript, Docker
Idioma inicial: Português

O que estamos construindo
O ViralPost Studio será uma aplicação web em Flask que transforma um briefing em um post visual pronto para revisão, combinando texto gerado por uma integração autorizada com o ViralAI e imagens obtidas pela API oficial do Pinterest.

O sistema poderá usar um endpoint externo de inferência para ranquear as imagens encontradas conforme sua relevância visual e semântica para o briefing. Groq ou outro provedor compatível poderá ser usado quando oferecer um modelo e endpoint adequados; a integração deve ser configurável por variáveis de ambiente e não pode depender de um provedor específico.

Foco atual — MVP pronto para construção
Construir o fluxo funcional mínimo:

briefing → geração de texto → busca de imagens no Pinterest → ranking opcional das imagens → seleção → prévia editável → download

O MVP deve incluir:

aplicação Flask executável localmente e em Docker;
interface web responsiva;
formulário de briefing;
camada de integração desacoplada para o ViralAI;
integração server-side com a API oficial do Pinterest;
ranking opcional das imagens por endpoint de inferência;
prévia vertical editável;
cópia do texto e download da prévia;
configuração por variáveis de ambiente;
tratamento de erros, logs seguros e documentação de execução.
O MVP não inclui publicação automática em TikTok/Pinterest, agendamento, geração de vídeo, scraping, automação não autorizada de login via Discord ou replicação exata de conteúdo de terceiros.

1. Objetivos
Objetivos do MVP
Permitir criar um post a partir de um briefing.
Integrar o Pinterest somente por sua API oficial.
Integrar o ViralAI somente por API, OAuth ou método oficialmente autorizado.
Oferecer ranking opcional das imagens retornadas.
Funcionar sem credenciais durante desenvolvimento, usando adaptadores mock.
Ser executável com docker compose.
Manter tokens e chaves exclusivamente no backend.
Permitir revisão humana antes da exportação.
Fora do escopo
Publicação automática em redes sociais.
Scraping de Pinterest, ViralAI, Discord ou TikTok.
Captura de senha, cookies ou sessão do Discord.
Geração de vídeos ou carrosséis.
Banco de imagens próprio.
Sistema de cobrança.
Multiusuário avançado e administração.
2. Arquitetura técnica
text
Browser
   |
   v
Flask Web App
   |
   +--> Content Provider Adapter
   |       +--> ViralAI provider
   |       +--> Mock provider
   |
   +--> Pinterest API Client
   |
   +--> Image Ranking Adapter
   |       +--> Inference endpoint
   |       +--> Groq-compatible provider, se suportado
   |       +--> Local deterministic fallback
   |
   +--> Preview Renderer
   |
   +--> Optional persistence layer
Princípios técnicos
Python 3.11 ou versão estável compatível com as dependências.
Flask com aplicação organizada por módulos.
Jinja2 para renderização server-side, com JavaScript leve para interações.
Cliente HTTP com timeout, retry limitado e tratamento de status.
Interfaces abstratas para ViralAI, Pinterest e ranking.
Modo mock ativável sem credenciais externas.
Nenhuma chave secreta no frontend.
Dockerfile reproduzível e docker-compose.yml para execução local.
Armazenamento inicial em memória ou SQLite, conforme a menor complexidade necessária.
Arquivos temporários de imagens devem ser controlados e não expostos indevidamente.
3. Configuração por ambiente
A aplicação deve documentar e ler variáveis como:

env
FLASK_ENV=production
SECRET_KEY=change-me
PINTEREST_ACCESS_TOKEN=
VIRALAI_API_BASE_URL=
VIRALAI_API_KEY=
VIRALAI_AUTH_MODE=mock
RANKING_ENABLED=true
RANKING_PROVIDER=mock
RANKING_API_BASE_URL=
RANKING_API_KEY=
RANKING_MODEL=
REQUEST_TIMEOUT_SECONDS=20
Os nomes finais podem ser ajustados durante a implementação, mas devem ser centralizados, documentados em .env.example e nunca ter valores secretos commitados.

4. Fluxo funcional
Usuário abre a aplicação.
Preenche tema, nicho, público, tom, objetivo, formato, idioma e palavras-chave.
Flask valida o formulário.
O provider de conteúdo gera título, corpo, legenda, CTA, hashtags e alt text.
O cliente Pinterest busca imagens relacionadas.
Se o ranking estiver habilitado, o sistema envia metadados permitidos das imagens ao endpoint configurado.
O ranking retorna pontuações e justificativas curtas ou somente pontuações.
O sistema ordena os resultados e permite seleção manual.
A aplicação monta uma prévia vertical.
Usuário edita o texto e escolhe outra imagem se quiser.
Usuário copia a legenda ou baixa a prévia.
A origem da imagem permanece visível ou disponível na exportação quando aplicável.
5. Ranking de imagens
Requisito
O ranking deve melhorar a ordem das imagens retornadas, mas nunca impedir a escolha manual pelo usuário.

Entrada possível
Briefing textual;
Título gerado;
Palavras-chave;
Descrição, título e link do Pin;
Metadados permitidos pela API.
Evitar enviar imagens completas para um endpoint textual se o provedor não suportar visão ou se isso for desnecessário.

Saída esperada
json
{
  "results": [
    {
      "image_id": "id",
      "score": 0.92,
      "reason": "Composição e tema alinhados ao briefing"
    }
  ]
}
Fallback
Se o endpoint estiver indisponível, exceder limite, não tiver credencial ou retornar formato inválido:

não interromper a geração;
manter a ordem original ou aplicar ranking determinístico local;
informar discretamente que o ranking avançado não foi aplicado;
registrar erro sem revelar segredos.
Observação sobre Groq
A implementação deve tratar Groq como um provedor opcional e configurável, não como dependência obrigatória. A equipe deve confirmar se o modelo/end-point escolhido suporta o tipo de inferência necessário e se o uso é compatível com os termos do serviço. Não assumir que “free model” significa disponibilidade, gratuidade permanente ou autorização para uso comercial.

6. Requisitos funcionais
RF-01 — Briefing
Campos:

Tema — obrigatório;
Nicho;
Público-alvo;
Tom de voz — obrigatório;
Objetivo;
Formato — obrigatório;
Idioma — obrigatório;
Palavras-chave.
RF-02 — Geração de conteúdo
Retornar:

Título;
Texto principal;
Legenda;
CTA;
Hashtags;
Texto alternativo.
O resultado deve ser editável.

RF-03 — Busca no Pinterest
Usar apenas API oficial;
Executar no backend;
Respeitar token, escopos, limites e políticas;
Exibir imagem, título, URL do Pin e origem;
Permitir seleção manual.
RF-04 — Ranking
Ser ativável por configuração;
Possuir adapter para endpoint externo;
Possuir mock e fallback local;
Não expor prompts ou chaves;
Não substituir a seleção do usuário.
RF-05 — Prévia
Formato vertical;
Imagem;
Título;
Texto resumido;
CTA;
Edição antes da exportação;
Responsividade mobile.
RF-06 — Exportação
Copiar legenda;
Copiar hashtags;
Baixar PNG ou JPEG;
Incluir fonte/atribuição quando aplicável.
RF-07 — Saúde e diagnóstico
Disponibilizar endpoint interno ou página de saúde que informe apenas:

aplicação ativa;
modo de integração;
status não sensível dos provedores.
Nunca exibir tokens, prompts privados ou valores secretos.

7. Endpoints Flask sugeridos
text
GET  /                         Landing ou criador
GET  /create                   Formulário de briefing
POST /generate                 Gera texto e busca imagens
POST /rank                     Executa ranking opcional
GET  /preview/<id>             Exibe prévia
POST /preview/<id>/export      Exporta arquivo
GET  /health                   Health check
Os endpoints podem ser reorganizados pelo engenheiro, desde que o fluxo permaneça claro e testável.

8. Critérios de aceitação
 docker compose up --build inicia a aplicação.
 .env.example documenta todas as configurações.
 A aplicação funciona em modo mock sem credenciais.
 O briefing é validado.
 O adapter de conteúdo retorna estrutura consistente.
 O cliente Pinterest é server-side e trata erros.
 O ranking pode ser desligado por ambiente.
 O ranking possui fallback funcional.
 O usuário pode escolher manualmente a imagem.
 A prévia é editável.
 O usuário consegue copiar e baixar o conteúdo.
 A origem da imagem aparece na interface.
 Nenhum segredo aparece no frontend, logs ou repositório.
 Existem testes unitários para validação, adapters e fallback.
 Existe README com instalação, configuração e execução.
 Não há scraping nem automação de login não autorizada.
9. Dependências e riscos
A integração ViralAI depende de uma API ou método oficialmente autorizado.
O token do Pinterest deve possuir escopos adequados.
Imagens do Pinterest podem não ter licença de reutilização comercial.
Endpoints gratuitos podem possuir limites, instabilidade ou mudar de disponibilidade.
O ranking é um recurso auxiliar e não deve ser apresentado como avaliação objetiva de qualidade.
Uso comercial de qualquer provedor deve ser validado segundo seus termos atuais.
10. Definition of Done
O MVP estará pronto para revisão quando:

O código Flask estiver organizado e documentado.
Docker e execução local funcionarem.
O fluxo completo funcionar em modo mock.
As integrações externas estiverem isoladas por adapters.
Pinterest, ViralAI e ranking puderem ser configurados sem alterar código.
O fallback permitir demonstração mesmo sem endpoint de inferência.
Testes automatizados básicos passarem.
A interface permitir concluir o fluxo briefing → prévia → exportação.
O README explicar credenciais, limitações e uso autorizado das APIs.
O resultado tiver sido verificado em navegador e em container.
Próximo passo
Implementar o MVP técnico em uma única entrega focada, começando pelo esqueleto Flask/Docker, adapters mock, fluxo de briefing, prévia e exportação; depois conectar e testar os provedores externos quando as credenciais e os métodos autorizados estiverem disponíveis.