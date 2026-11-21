# Plataforma de operações isoladas na VPS

Análise do "Manual de Implantação: Operations Infrastructure Platform v1.0" e como ele foi adaptado para ser viável sobre o que já existe e funciona.

Princípio mantido: **administração central, execução separada.** O isolamento serve à segurança, à organização e à continuidade: uma operação que quebra, trava ou é parada não afeta as outras. **Não é anonimato** perante serviços externos. Todas as operações saem do mesmo servidor, do mesmo app no Google e dos mesmos donos, e a ferramenta não tenta esconder isso.

## O que muda em relação ao manual, e por quê

| Manual | Decisão | Motivo |
|---|---|---|
| Painel Astro + API Node.js | **Mantém o painel atual** (FastAPI na Vercel) como Control Plane | Já está em produção, com login, operações, fila, Acessos e dados. Reescrever em outra linguagem dobra o código sem ganho para o usuário. |
| Docker Controller acessado pela API | **Agente na VPS que puxa o estado desejado do banco** (modelo *pull*) | A Vercel não alcança a VPS, e nem deve: nenhuma porta fica aberta e o socket do Docker não sai da máquina. O painel grava o que deve acontecer, e o agente executa e devolve o estado real. |
| Redis + BullMQ | **Mantém a fila no Postgres**, com escopo por operação | A fila atual já tem retry com backoff, idempotência, deduplicação, controle de concorrência e retomada. Redis seria mais um serviço para manter numa VPS pequena, sem ganho neste volume. Se o volume exigir, a troca fica isolada em `core/queue.py`. |
| Prometheus + Grafana + cAdvisor | **Agente coleta CPU, memória e disco** (do servidor e de cada container) e o painel mostra | Grafana e Prometheus juntos pesam centenas de MB de RAM. Na v1, o agente cobre o que o manual pede. Ficam como opção futura (Task 37). |
| PostgreSQL próprio na VPS | **Mantém o Neon** | Já tem backup e restauração do próprio Neon, e o banco é compartilhado com o painel. Um Postgres local fica como opção de "isolamento adicional" (Task 36). |
| Row-Level Security | **Fase 2** (Task 36). Na v1, o escopo é imposto no código | RLS exige um papel de banco por operação e políticas em todas as tabelas. É o passo certo, mas grande. Na v1, cada worker só pega tarefas da sua operação, e o painel mostra isso honestamente. |
| Imagens versionadas em registro | **Imagens com a tag do commit** (`fea-worker:<commit>`), construídas na própria VPS | Sem registro privado nem credencial extra. Cada operação fixa uma versão; atualizar ou voltar é trocar a tag. |
| Backup "fora da VPS" | **v1: backup local por operação + dump diário do banco.** Cópia externa (R2) na Task 35 | O R2 tem limite grátis que a ferramenta controla. A cópia externa entra quando o tamanho for medido. |

## Arquitetura

```
 Painel (Vercel)  ──grava estado desejado──▶  Neon (Postgres)  ◀──lê e reporta──  Agente (VPS)
   iniciar/parar/limites/versão                 operation_runtimes                       │
                                                infra_servers                            ▼
                                                jobs (com operation_id)        docker compose por operação
                                                                                ├─ fea-nucleo   (agenda, limpeza, backup)
                                                                                ├─ fea-op-1     (busca, edição, publicação)
                                                                                └─ fea-op-2     (busca, edição, publicação)
```

- **Control Plane:** painel (telas e decisões) + agente (Operations Manager, Docker Controller, Resource Manager, Health Monitor e Version Manager num processo só, na VPS).
- **Execution Plane:** um projeto Docker Compose por operação (`fea-op-<id>`), com rede própria, limites de CPU e memória, volumes próprios, sem portas abertas, sem privilégios extras (`no-new-privileges`, sem capabilities) e sistema de arquivos só de leitura, exceto as pastas da operação.
- **Núcleo** (`fea-nucleo`): as rotinas que não pertencem a nenhuma operação (agendador, limpeza, renovação de tokens, backup do banco).
- **Data Plane:** Neon (dados e fila), R2 (vídeos), `/opt/fea/operations/op-<id>/` (mídia temporária, logs, estado e backups de cada operação).

## Migração do celular para a VPS: um comando

Na VPS, o comando gerado em **Acessos → Workers** instala tudo: Docker, firewall, código, imagem, núcleo e agente. O agente sobe um ambiente para cada operação ativa e marca a plataforma como ativa. Os workers do celular percebem isso sozinhos e param, com a mensagem "migrado para a VPS". Não é preciso fazer mais nada no celular.

## Critérios de aceitação (seção 15 do manual), com o estado real

| Critério | Como é atendido | Situação |
|---|---|---|
| Criar operação sem terminal | Painel → Ambiente → Iniciar; o agente gera o Compose e sobe | v1 |
| Parar uma sem interromper as outras | Projeto Compose separado por operação | v1 (testado com Docker real) |
| Dados de uma não consultáveis por outra | v1: escopo no código (cada worker só pega tarefas da sua operação). **Garantia no banco só com RLS** | Parcial → Task 36 |
| Sem comunicação lateral | Rede Docker própria por operação, sem portas | v1 (testado) |
| Credenciais fora dos logs | Filtro de segredos no log (inclusive `?key=` em URLs) | v1 |
| Atualização individual | Versão fixada por operação (tag do commit) | v1 |
| Falha visível no painel | Agente reporta o estado dos containers e o erro; painel mostra em vermelho | v1 |
| Restaurar backup | Backup e restauração dos arquivos da operação; banco pelo dump diário ou pelo Neon | Parcial → Task 35 |
| Reinstalar sem perder dados | Instalador idempotente; dados no Neon, no R2 e em `/opt/fea` | v1 |
