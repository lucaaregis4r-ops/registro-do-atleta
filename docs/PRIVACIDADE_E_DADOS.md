# Privacidade e dados

Este repositorio foi preparado para demonstracao publica sem publicar dados operacionais.

## O que nao deve entrar no Git

- bancos SQLite e respectivos backups;
- planilhas XLS/XLSX e exportacoes CSV reais;
- snapshots de fontes, arquivos ZIP e relatorios gerados;
- nomes, identificadores ou historicos de atletas;
- IDs e URLs de planilhas privadas;
- tokens, chaves de API, contas de servico e arquivos `.env`;
- logs locais que possam conter caminhos, payloads ou identificadores.

O `.gitignore` cobre esses formatos comuns, mas ele nao substitui uma revisao manual antes de cada publicacao.

## Checklist antes de enviar dados de exemplo

1. Prefira dados totalmente sinteticos, nao apenas nomes anonimizados.
2. Nao preserve combinacoes raras de data, modalidade, categoria e evento que permitam reidentificacao.
3. Nao copie IDs originais nem hashes derivados de informacao pessoal.
4. Procure segredos e caminhos locais no conteudo a ser commitado.
5. Revise tambem o historico do Git: apagar um arquivo em um commit novo nao o remove dos commits anteriores.

## Escopo da demo

`apps/dashboard/public/demo-data.json` contem somente personagens e valores ficticios. Ele existe para permitir que a interface seja avaliada sem conectar qualquer fonte externa.

## Uso responsavel

O projeto nao substitui avaliacao de profissionais de saude ou esporte. Limiares e alertas precisam de validacao metodologica e contextual antes de qualquer uso real.
