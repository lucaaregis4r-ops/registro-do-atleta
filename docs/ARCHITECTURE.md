# Arquitetura do Registro do Atleta

## Problema que o projeto resolve

Dados esportivos costumam nascer em planilhas e formularios mantidos por areas diferentes. O desafio nao e apenas exibir graficos: e saber se dois registros pertencem ao mesmo atleta, preservar a origem de cada valor, tratar datas inconsistentes e permitir que uma pessoa revise ambiguidades sem apagar o historico.

O Registro do Atleta organiza esse fluxo em camadas pequenas e testaveis.

## Camadas

### 1. Auditoria e ingestao

As fontes historicas sao lidas sem alteracao. O sistema calcula hashes, inventaria arquivos, cria snapshots e registra metadados de execucao. A ingestao para staging e idempotente para evitar duplicacao ao processar a mesma fonte novamente.

### 2. Identidade longitudinal

Nomes sao normalizados e vinculados a um cadastro canonico. Casos de baixa confianca entram em uma fila de revisao humana. Alias, decisoes e autoria da revisao ficam registrados para auditoria.

### 3. Dominios esportivos

Os registros de PSR, fisioterapia e avaliacoes fisicas sao normalizados em tabelas proprias. As transformacoes mantem a referencia ao registro de origem.

### 4. Qualidade e alertas

Regras deterministicas detectam datas invalidas, possiveis duplicidades e sinais configurados. Alertas relacionados sao agrupados em episodios, permitindo distinguir novidade, persistencia, escalada e resolucao.

### 5. Revisao e comunicacao

API e dashboard oferecem filas para identidade, datas, duplicidades, alertas e literatura. Briefings e relatorios sao gerados de forma deterministica para facilitar a rotina da equipe.

### 6. Operacao resiliente

SQLite opera localmente com cuidados de concorrencia, lock de pipeline, backup consistente, restauracao com verificacao de integridade e relatorios de prontidao operacional.

### 7. IA com limites explicitos

O provedor de LLM e opcional e fica desabilitado por padrao. Ele pode apoiar resumo e explicacao, mas nao e autoridade unica para identidade, correcao de datas, aprovacao de literatura ou persistencia critica.

## Fluxo de dados

```text
XLSX / fontes configuradas
        |
        v
auditoria -> snapshots -> staging
                          |
                          v
                   identidade canonica
                    |              |
                    |              +-> revisao humana + trilha de auditoria
                    v
          PSR / fisio / avaliacoes
                    |
                    v
      qualidade -> alertas -> episodios
                    |             |
                    v             v
                 API local     briefing/relatorios
                    |
                    v
                 dashboard
```

## Tecnologias

- Python 3.12+
- biblioteca padrao e SQLite no nucleo;
- FastAPI e Uvicorn como dependencias opcionais da API;
- HTML, CSS e JavaScript no dashboard;
- Pytest na verificacao automatizada;
- Streamlit como interface alternativa opcional em desenvolvimento.

## Limites desta versao publica

- nao inclui fontes reais, bancos, snapshots, planilhas ou relatorios operacionais;
- a demo visual usa somente dados sinteticos;
- conectores precisam ser configurados pelo usuario;
- regras de alerta sao demonstracoes tecnicas e nao orientacao clinica;
- modelos estatisticos avancados permanecem condicionados ao gate metodologico.
