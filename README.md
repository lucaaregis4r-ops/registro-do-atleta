# Registro do Atleta

Projeto local para organizar fontes esportivas dispersas em um registro longitudinal, auditavel e revisavel dos atletas.

O foco do projeto nao e um chatbot. O produto central e uma base confiavel: ingestao com preservacao das fontes, normalizacao por dominio, resolucao de identidade com revisao humana, alertas deterministicos, relatorios e operacao resiliente em SQLite.

> Esta edicao publica contem somente codigo e dados sinteticos de demonstracao. Planilhas, bancos, snapshots, nomes de atletas, credenciais e configuracoes reais nao fazem parte do repositorio.

## Demo em dois minutos

Requisito: Python 3.12 ou superior.

No Windows:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_demo.ps1
```

No Linux ou macOS:

```bash
sh scripts/start_demo.sh
```

Abra `http://127.0.0.1:8080` e selecione **Demo sintetica**. Essa experiencia e somente leitura e usa personagens e indicadores ficticios.

Tambem e possivel executar diretamente:

```bash
python -m http.server 8080 --bind 127.0.0.1 --directory apps/dashboard
```

## O que esta implementado

- inventario e hashing SHA-256 de fontes historicas sem alterar os arquivos brutos;
- snapshots e staging idempotente em SQLite;
- cadastro longitudinal e resolucao auditavel de identidade;
- normalizacao de PSR, fisioterapia e avaliacoes fisicas;
- achados de qualidade, datas efetivas e deteccao de possiveis duplicidades;
- alertas deterministicos, episodios e briefing orientado por mudancas;
- filas de revisao humana para identidade, datas, duplicidades, alertas e literatura;
- API local FastAPI e dashboard responsivo;
- backup, restauracao verificada, lock de processo e relatorios operacionais;
- integracao opcional com LLM, desabilitada por padrao e sem autoridade sobre persistencia critica;
- gate metodologico antes de analises estatisticas avancadas.

## Arquitetura resumida

```text
fontes brutas (somente leitura)
          |
          v
 snapshots + staging SQLite
          |
          v
 identidade auditavel ----> revisao humana
          |
          v
 dominios normalizados ----> qualidade e duplicidades
          |
          v
 alertas deterministicos -> episodios -> briefing
          |
          +---------------> API local -> dashboard
```

Mais detalhes em [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Instalar e testar

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev,api]"
python -m pytest -q
```

A API pode ser iniciada com um banco local vazio:

```bash
registro-do-atleta run-api --database data/database/registro_atleta.db
```

Depois, acesse `http://127.0.0.1:8000/dashboard/`. Para operacao real, configure fontes proprias e leia primeiro [docs/PRIVACIDADE_E_DADOS.md](docs/PRIVACIDADE_E_DADOS.md).

## Principios de projeto

1. Fonte bruta e imutavel.
2. Persistencia critica e deterministica e auditavel.
3. Decisoes ambiguas passam por revisao humana.
4. LLM resume e explica; nao decide sozinho o que vira verdade no banco.
5. Analise avancada so e liberada depois de um gate de qualidade e metodologia.

## Estado do projeto

Este e um projeto em desenvolvimento e uma demonstracao tecnica, nao um dispositivo medico nem uma ferramenta de decisao clinica. Os limites e alertas de exemplo nao devem ser usados como recomendacao profissional.

## Licenca

Distribuido sob a [Licenca MIT](LICENSE). E permitido usar, copiar, modificar e redistribuir o codigo, inclusive em projetos comerciais, desde que o aviso de autoria e a licenca sejam preservados.
