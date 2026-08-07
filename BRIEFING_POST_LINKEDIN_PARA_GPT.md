# Briefing para criar o post do LinkedIn

Copie este documento para o GPT, complete os campos entre colchetes e acrescente o link do repositorio quando ele estiver publicado.

---

## Contexto do autor

- Nome: [SEU NOME]
- Papel no projeto: [EX.: idealizador e desenvolvedor]
- Area profissional: [SUA AREA]
- Tempo aproximado dedicado: [TEMPO OU PERIODO, SE QUISER DIVULGAR]
- Motivacao pessoal: [POR QUE VOCE COMECOU]
- Link do GitHub: [URL]
- Link da demo, imagens ou video: [URL, SE HOUVER]

## O que e o Registro do Atleta

O Registro do Atleta e um sistema local para organizar dados esportivos em um historico longitudinal e auditavel. O produto principal nao e um chatbot: e uma base confiavel dos atletas.

O projeto nasceu do problema de organizar informacoes esportivas dispersas em planilhas e formularios. Para que os dados sejam realmente uteis, nao basta coloca-los em um dashboard. E necessario preservar a origem, identificar corretamente cada atleta ao longo do tempo, tratar datas e duplicidades, registrar decisoes humanas e impedir que automacoes transformem incerteza em “verdade” silenciosamente.

## O que o programa faz

- inventaria fontes historicas e calcula hashes sem modificar os arquivos originais;
- cria snapshots e uma camada de staging idempotente em SQLite;
- normaliza nomes e constroi uma identidade longitudinal dos atletas;
- envia casos ambiguos para revisao humana e registra a trilha da decisao;
- estrutura dados de PSR, fisioterapia e avaliacoes fisicas;
- detecta problemas de qualidade, datas invalidas e possiveis duplicidades;
- gera alertas deterministicos e agrupa sinais relacionados em episodios;
- distingue sinais novos, persistentes, escalados e resolvidos;
- produz briefing e relatorios operacionais orientados por mudancas;
- disponibiliza API local e dashboard responsivo;
- possui backup, restauracao verificada, lock de execucao e verificacoes de integridade;
- permite uso opcional de LLM para resumir e explicar, sem entregar a ele autoridade unica sobre a persistencia critica;
- bloqueia analises estatisticas avancadas enquanto requisitos de qualidade e validacao metodologica nao forem atendidos.

## Decisoes tecnicas que merecem destaque

1. **Auditabilidade antes de sofisticacao.** Cada transformacao importante deve poder ser rastreada ate a fonte e a execucao que a produziu.
2. **Human-in-the-loop.** Identidade, datas ambiguas, duplicidades e aprovacao de literatura possuem fluxos de revisao humana.
3. **Fontes brutas preservadas.** A automacao le e cria derivados; nao “corrige” planilhas originais silenciosamente.
4. **IA com limites.** O LLM e assistente de comunicacao e pesquisa, nao autoridade final sobre fatos sensiveis.
5. **Operacao local e resiliente.** SQLite, backup consistente, restauracao verificada e controle de concorrencia foram tratados como parte do produto.
6. **Gate metodologico.** O sistema prefere dizer “ainda nao e confiavel modelar isso” a exibir uma previsao sofisticada sem base suficiente.

## Tecnologias

Python 3.12+, SQLite, FastAPI, Uvicorn, HTML, CSS, JavaScript, Pytest e Streamlit opcional. O nucleo foi dividido em modulos pequenos para auditoria, ingestao, identidade, dominios, qualidade, alertas, relatorios, operacao, API e integracao opcional com LLM.

## O que esta no GitHub

A versao publica contem o codigo, testes automatizados, documentacao de arquitetura e um dashboard com dados totalmente sinteticos. Nao contem nomes de atletas, planilhas, bancos, snapshots, credenciais, IDs de fontes ou relatorios reais.

## O que aprendi construindo

Use estas ideias, selecionando apenas as que combinarem com a minha experiencia:

- o trabalho mais dificil em dados reais costuma ser identidade, proveniencia e qualidade, nao o grafico final;
- automatizar sem trilha de auditoria pode acelerar o erro;
- revisao humana funciona melhor quando e parte explicita da arquitetura;
- um sistema confiavel precisa saber quando nao tem base metodologica para responder;
- operacao, backup e restauracao tambem sao funcionalidades do produto;
- IA e mais valiosa quando seus limites sao desenhados desde o inicio.

## Tom desejado

- pessoal, honesto e tecnicamente interessante;
- orgulhoso do trabalho, sem parecer propaganda exagerada;
- acessivel para pessoas de tecnologia, dados e esporte;
- mostrar a jornada e as decisoes, nao apenas listar funcionalidades;
- evitar frases genericas como “revolucionar o esporte com IA”;
- nao inventar usuarios, resultados, percentuais, impacto clinico ou uso em producao;
- deixar claro que dados publicos da demo sao sinteticos;
- explicar que o projeto esta em desenvolvimento.

## Prompt para o GPT

Crie um post em portugues do Brasil para o LinkedIn com base exclusivamente neste briefing. Escreva em primeira pessoa, com 1.300 a 1.900 caracteres, paragrafos curtos e uma abertura forte, mas sem clickbait. Conte primeiro o problema real: construir confianca em dados esportivos dispersos. Em seguida, apresente o Registro do Atleta e destaque tres decisoes que revelam maturidade de engenharia: banco longitudinal auditavel, revisao humana para ambiguidades e LLM sem autoridade sobre persistencia critica. Mencione brevemente o dashboard, a API local, testes e operacao resiliente. Inclua uma reflexao pessoal sobre o que aprendi. Termine convidando pessoas de esporte, ciencia de dados e engenharia a conhecer o repositorio e enviar feedback. Inclua o link [URL DO GITHUB]. Use no maximo cinco hashtags especificas. Nao use emojis em excesso, nao invente metricas e nao trate o sistema como dispositivo medico ou produto finalizado.

Depois do post principal, gere tambem:

1. uma versao curta de ate 700 caracteres;
2. tres opcoes de primeira frase;
3. uma sugestao de titulo para o repositorio;
4. uma legenda de ate 200 caracteres para acompanhar um video ou captura do dashboard;
5. cinco hashtags relevantes, sem hashtags genericas demais.

## Informacoes opcionais que melhoram muito o texto

Antes de gerar a versao final, eu posso acrescentar:

- uma dificuldade tecnica concreta que quase fez o projeto travar;
- uma decisao da qual me orgulho;
- uma imagem do dashboard com dados sinteticos;
- quanto tempo trabalhei no projeto;
- se foi um projeto individual ou colaborativo;
- que tipo de feedback ou oportunidade desejo receber com a publicacao.

---

## Observacao para revisao humana

Antes de publicar, confira todas as afirmacoes do texto gerado. Remova qualquer numero ou resultado que nao possa ser demonstrado pelo repositorio e substitua os campos entre colchetes.
