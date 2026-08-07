# Checklist para publicar no GitHub

Esta pasta foi montada por lista de inclusao. Nao mova arquivos do projeto privado para ca sem nova revisao.

## 1. Decisoes antes da publicacao

- [x] Nome definido: `registro-do-atleta`.
- [x] Licenca MIT adicionada, permitindo uso, copia, modificacao e redistribuicao com preservacao do aviso de autoria.
- [ ] Adicionar seu nome e formas de contato apenas se desejar torna-los publicos.
- [ ] Decidir se o repositorio sera publico imediatamente ou privado durante a ultima revisao.

## 2. Revisao local

Execute dentro desta pasta:

```powershell
rg -n -i "api.key|secret|password|bearer|private.key|docs.google.com/spreadsheets|Users\\" .
Get-ChildItem -Recurse -File -Include *.db,*.sqlite,*.sqlite3,*.xlsx,*.xls,*.csv,*.zip,*.pem,*.key
python -m pytest -q
```

O campo de senha da interface e os exemplos em documentacao podem aparecer na busca textual; o importante e confirmar que nao existe valor real.

## 3. Criar o repositorio local

```powershell
git init
git branch -M main
git add .
git status
git diff --cached --stat
git diff --cached
git commit -m "Publica demonstracao sanitizada do Registro do Atleta"
```

Leia a lista inteira exibida por `git status` antes do commit.

## 4. Enviar ao GitHub

Crie um repositorio vazio no GitHub, sem README ou `.gitignore` automaticos, e use os comandos fornecidos pela pagina. Em geral:

```powershell
git remote add origin https://github.com/SEU_USUARIO/SEU_REPOSITORIO.git
git push -u origin main
```

Comecar como repositorio privado permite conferir a pagina final antes de altera-lo para publico.

## 5. Conferencia final no GitHub

- [ ] A demo abre seguindo apenas o README.
- [ ] Nenhum arquivo real aparece na arvore ou no historico.
- [ ] A descricao do repositorio explica que os dados sao sinteticos.
- [ ] Os topicos do repositorio refletem o projeto, por exemplo: `sports-analytics`, `data-engineering`, `sqlite`, `fastapi`, `data-quality`, `human-in-the-loop`.
- [ ] O link do repositorio esta pronto para ser incluido no post do LinkedIn.
