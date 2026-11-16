# Tasks — Ferramenta de Operações de Vídeo

Fonte: artefato **"Especificação da Ferramenta — v2.1"** (https://claude.ai/artifact/GHvbjsWudPNWXgXHyUyEz5), seções 0 a 17.

## Legenda

- **Nível** (atenção): 1 a 5, sendo 5 o maior.
- **Status**: `-1` = nada (não iniciada) · `0` = em trabalho · `1` = concluída.

## Mapa de fases (da seção 15 da spec)

- **Base (antes da Fase 1):** Tasks 1, 2 e 3.
- **Fase 1 — Operação e coleta:** Tasks 4 a 8.
- **Fase 2 — Edição e aprovação:** Tasks 9 a 13.
- **Fase 3 — Distribuição:** Tasks 14 a 19 (YouTube primeiro).
- **Transversais:** Tasks 20 a 22.
- **Fase 4 — Expansão:** Task 23.
- **Pendências de decisão:** Task 24.

---

## Task 1: Fundação do projeto
Nível: 5
Status: -1

- Subtask 1.1: Repositório e estrutura de pastas (`app/`, `worker/`, `migrations/`, `storage/`, `tests/`).
- Subtask 1.2: Ambiente de desenvolvimento com Docker Compose (serviços `web`, `worker`, `postgres`).
- Subtask 1.3: Configuração por variáveis de ambiente, incluindo a chave de criptografia dos tokens.
- Subtask 1.4: Aplicação FastAPI com Jinja2 + HTMX e layout base responsivo.
- Subtask 1.5: Ferramenta de migrações de banco (a escolher) e migração inicial vazia.
- Subtask 1.6: Autenticação do usuário único (login simples, sem papéis).
- Subtask 1.7: Logging estruturado sem exibir tokens ou segredos.

## Task 2: Banco de dados (12 tabelas, seção 12)
Nível: 5
Status: -1

- Subtask 2.1: Tabelas `operations` e `operation_configs` (config em JSONB, versão por salvamento).
- Subtask 2.2: Tabelas `accounts` e `operation_accounts` (relação muitos-para-muitos).
- Subtask 2.3: Tabelas `sources` e `executions` (com `execution_id` e `config_version_id`).
- Subtask 2.4: Tabelas `items` e `renders` (aprovação guardada no item: `approved_render_id`, `approved_account_ids`).
- Subtask 2.5: Tabelas `batches` e `publish_jobs`, com restrição única `(render_id, account_id)`.
- Subtask 2.6: Tabela `jobs` com `idempotency_key` única e índices em `status` e `run_at`.
- Subtask 2.7: Tabela `events` (auditoria e log).
- Subtask 2.8: Índice único `(source_id, external_id)` e índices para `sha256` e `phash`.
- Subtask 2.9: Constraints de status conforme as máquinas de estado (item e envio).

## Task 3: Worker e fila de tarefas
Nível: 5
Status: -1

- Subtask 3.1: Captura de tarefa com `FOR UPDATE SKIP LOCKED`, ordenando por prioridade e `run_at`.
- Subtask 3.2: Loops por tipo com concorrência: `collect` (2), `render` (1 por núcleo livre, padrão 2), `publish` (1 por conta), `scheduler_tick` (1).
- Subtask 3.3: Idempotência por chave: `collect:{execution_id}`, `render:{item_id}:{config_version}`, `publish:{publish_job_id}`.
- Subtask 3.4: Reexecução segura: tarefa que reaparece detecta o efeito existente e termina sem refazer.
- Subtask 3.5: `scheduler_tick` a cada 1 minuto (promove `planned`, reavalia `pending_capacity` por dia, verifica `uncertain`).
- Subtask 3.6: Worker não pega tarefas de execução pausada; tarefas em andamento terminam.
- Subtask 3.7: Prioridade: `alta`, `normal`, `baixa`, herdada por itens e tarefas.

## Task 4: Operações
Nível: 4
Status: -1

- Subtask 4.1: CRUD de operação (nome, status).
- Subtask 4.2: Configuração JSON versionada; cada salvamento cria nova versão e as anteriores nunca mudam (REQ-UI-003).
- Subtask 4.3: Estados `draft`, `active`, `paused`, `archived`.
- Subtask 4.4: Regras: `paused` não aceita Play novo, envios planejados ficam em espera; `archived` é somente leitura.
- Subtask 4.5: Formulário único com seções (sem assistente de várias etapas).
- Subtask 4.6: Tela de detalhe com abas: Visão geral, Configuração, Fontes, Contas, Execuções, Histórico de versões.
- Subtask 4.7: Lista de operações com botão Play em cada linha.
- Subtask 4.8: Teste: duas operações com configurações diferentes rodando nos mesmos motores (critério 1).

## Task 5: Fontes e conectores
Nível: 4
Status: -1

- Subtask 5.1: Cadastro de fonte por operação (`type`, `reference`, `permission_note`, `status`, `cursor`, `last_error`).
- Subtask 5.2: `permission_note` obrigatório; sem ele, itens entram como `pending_permission` (REQ-UI-004).
- Subtask 5.3: Interface `SourceConnector` (`fetch`, `download`) e modelo `RawItem` (`external_id`, `url`, `author`, `published_at`, `media_type`, `text`).
- Subtask 5.4: Conector de upload manual.
- Subtask 5.5: Conector Reddit pela API oficial, apenas em comunidades com autorização registrada.
- Subtask 5.6: Erro temporário: até 3 tentativas com espera crescente.
- Subtask 5.7: Credencial inválida ou fonte removida: `status=error`, aparece no dashboard, execução segue com as outras fontes.

## Task 6: Execução (Play)
Nível: 5
Status: -1

- Subtask 6.1: Tela do Play com quantidade X, orçamento de busca, fontes (todas marcadas), critério e prioridade.
- Subtask 6.2: Criar `executions` com `config_version_id` congelada, X, orçamento e `status=running`.
- Subtask 6.3: Tarefa `collect`: para ao atingir X elegíveis, ao estourar o orçamento ou ao esgotar as fontes.
- Subtask 6.4: Critério "mais recentes" (padrão).
- Subtask 6.5: Critério "priorizar heat tags": examina até `min(orçamento, 3 × X)`, seleciona os X de maior score; o resto fica como `eligible` com motivo "reserva".
- Subtask 6.6: "Processar selecionados" para processar itens reserva depois.
- Subtask 6.7: Fechamento: `completed` se chegou a X; `partial` com `shortfall_reason` caso contrário.
- Subtask 6.8: Contadores por `COUNT` sobre `items` (examinados, duplicados, rejeitados, pendentes de permissão, elegíveis, renderizados, aguardando aprovação, com erro).
- Subtask 6.9: Controles: pausar, retomar, cancelar (não apaga registros), reexecutar como novo Play com novo `execution_id`.
- Subtask 6.10: Execuções simultâneas da mesma operação permitidas.

## Task 7: Itens, validação, deduplicação e classificação
Nível: 5
Status: -1

- Subtask 7.1: Máquina de estados do item implementada conforme a tabela da seção 6.1.
- Subtask 7.2: Checagem de formato, duração (`max_duration_s`), palavra bloqueada e "fora do nicho" → `rejected`.
- Subtask 7.3: Deduplicação em ordem:
  - Subtask 7.3.1: Mesmo item externo `(source_id, external_id)` — escopo da fonte.
  - Subtask 7.3.2: Mesmo arquivo por `sha256` — escopo global.
  - Subtask 7.3.3: Imagem parecida por `phash` com distância ≤ 6 — escopo global.
- Subtask 7.4: pHash de vídeo sobre 3 quadros (10%, 50%, 90% da duração).
- Subtask 7.5: Duplicado de outra operação recebe `duplicate` com `duplicate_of`.
- Subtask 7.6: Classificação: score = tags (1) + heat tags (2) encontradas no texto ou título original; score 0 com tags configuradas → `rejected`.
- Subtask 7.7: Permissão: item herda `permission_note` da fonte; sem permissão vai para `pending_permission`; liberar ou rejeitar em lote na fila.

## Task 8: Filas
Nível: 4
Status: -1

- Subtask 8.1: Fila geral com colunas: item, operação, execução, etapa/estado, prioridade, score, data, erro, ação.
- Subtask 8.2: Fila da operação como a mesma tela com filtro `operation_id` (REQ-QUEUE-003).
- Subtask 8.3: Filtros por operação e por etapa.
- Subtask 8.4: Estados visíveis: encontrado, em validação, pendente de autorização, elegível, em edição, em correção, aguardando aprovação, aprovado, rejeitado, agendado, publicado, falha (REQ-QUEUE-005).
- Subtask 8.5: Seleção em lote com resumo antes de confirmar (REQ-UI-005).
- Subtask 8.6: Ordenação por prioridade da execução, depois por score.

## Task 9: Renderização (FFmpeg)
Nível: 4
Status: -1

- Subtask 9.1: Presets: canvas 1080×1920 (9:16), `frame_png`, `title_style`, `audio`.
- Subtask 9.2: Comando FFmpeg: normalização do canvas, fit (`cover`, `contain`, `blur_background`), sobreposição do frame, título com `drawtext` na margem segura, áudio (`keep`, `mute`, `normalize`), saída H.264/AAC MP4.
- Subtask 9.3: Imagens estáticas viram vídeo de N segundos conforme o preset.
- Subtask 9.4: Tabela `renders`: cada render cria nova versão e nunca sobrescreve a anterior.
- Subtask 9.5: Organização do storage: `operations/{op}/items/{item}/original.*` e `.../renders/{versão}.mp4`.
- Subtask 9.6: Storage em disco local, com abstração pronta para Cloudflare R2.

## Task 10: Títulos e metadados
Nível: 3
Status: -1

- Subtask 10.1: Cadeia de Markov de ordem 2 treinada no `corpus_file`; geração de N candidatos.
- Subtask 10.2: Filtros: `max_chars`, `blocked_words`, sem cópia exata de linha do corpus, sem repetir títulos já usados na operação.
- Subtask 10.3: Primeiro candidato válido; se nenhum passar, `fallback_templates` aleatório; registrar `title_method` (`markov`, `fallback`, `manual`).
- Subtask 10.4: Campos `visual_title` (dentro do vídeo) e `publication_title` (enviado à plataforma), editáveis separadamente na aprovação.
- Subtask 10.5: Alterar `visual_title` exige novo render; alterar `publication_title` ou descrição não exige.
- Subtask 10.6: Descrição a partir de `description_template`.
- Subtask 10.7: Hashtags por plataforma via `metadata.hashtags_by_platform`, com fallback para `hashtags`.

## Task 11: QA automático
Nível: 4
Status: -1

- Subtask 11.1: Verificação via `ffprobe`: arquivo abre, resolução e proporção batem com o preset, duração dentro do limite, stream de áudio presente quando `audio=keep`, título não vazio.
- Subtask 11.2: Aprovado → `awaiting_approval`; falhou → `needs_fix` com motivo.
- Subtask 11.3: Nova tentativa automática só para erro de processo, nunca para erro de conteúdo.

## Task 12: Editor
Nível: 3
Status: -1

- Subtask 12.1: Tela com player do render atual, lista de versões e formulário com os campos do preset (fit, título, áudio).
- Subtask 12.2: Botão "Renderizar nova versão"; cada ajuste gera nova versão.
- Subtask 12.3: Sem timeline: ajustes apenas por parâmetro (REQ-UI-006).

## Task 13: Aprovação
Nível: 5
Status: -1

- Subtask 13.1: Tela com player, origem, permissão, resultado do QA, títulos e descrição editáveis, contas autorizadas (REQ-UI-007).
- Subtask 13.2: Botões: aprovar, rejeitar, abrir editor, nova versão.
- Subtask 13.3: Aprovação vale para uma versão exata do render e para os destinos autorizados (REQ-APP-004).
- Subtask 13.4: Gerar render novo zera `approved_render_id` e `approved_account_ids`; reedição invalida a aprovação.
- Subtask 13.5: Aprovação em lote em modo grade, com resumo antes de confirmar; bloqueia itens com `needs_fix` ou sem permissão.
- Subtask 13.6: Se a operação exige aprovação, preparar não publica (REQ-APP-001).
- Subtask 13.7: Aprovar um conjunto e distribuir só os selecionados (critério 5).

## Task 14: Contas
Nível: 5
Status: -1

- Subtask 14.1: Tabela `accounts` e vínculo com operações via `operation_accounts` (REQ-ACC-001).
- Subtask 14.2: Conexão por OAuth oficial.
- Subtask 14.3: Token criptografado no banco com chave em variável de ambiente; nunca vai ao frontend nem aparece em log.
- Subtask 14.4: `daily_limit` configurado manualmente por conta.
- Subtask 14.5: Tela de contas: conectar, testar, pausar, revogar, ver operações associadas e envios recentes (REQ-UI-009).
- Subtask 14.6: Token inválido → `status=error` na conta e envios dela em `pending_capacity` ("reconectar conta"); demais contas não são afetadas.

## Task 15: Adaptadores de plataforma
Nível: 5
Status: -1

- Subtask 15.1: Interface `PlatformAdapter` (`publish`, `check`, `capabilities`: `direct_publish`, `native_schedule`, `drafts_only`).
- Subtask 15.2: Adaptador YouTube: OAuth, upload e controle da cota diária.
- Subtask 15.3: Confirmar a documentação atual da API antes de implementar (cota e limites).
- Subtask 15.4: Usar agendamento nativo da plataforma apenas quando o adaptador suportar.
- Subtask 15.5: Adaptadores TikTok e Instagram ficam para a Task 23.

## Task 16: Nova publicação
Nível: 5
Status: -1

- Subtask 16.1: Tela única com: lista de vídeos aprovados (checkbox e "selecionar todos"), contas da operação, intervalo em minutos, "Primeira publicação imediata", início (data/hora, aparece se a caixa estiver desmarcada).
- Subtask 16.2: Metadados por plataforma ou conta, opcionais e recolhidos por padrão: `title_override`, `description_override`; confirmação registrada em `events`.
- Subtask 16.3: Prévia da agenda por conta antes de confirmar.
- Subtask 16.4: Botão Confirmar.
- Subtask 16.5: Lista de lotes e lista de envios com os estados da Task 19.

## Task 17: Cálculo de horários
Nível: 5
Status: -1

- Subtask 17.1: Definição de T0: se primeira imediata → agora; senão, se há início → início; senão → agora + intervalo (REQ-DIST-013). Com intervalo 0 → agora.
- Subtask 17.2: Horário n = T0 + (n − 1) × intervalo, calculado por conta.
- Subtask 17.3: Janela de publicação (`window`): horário fora da janela vai para o início da próxima.
- Subtask 17.4: Limite diário: ao atingir `daily_limit`, envio vai para o primeiro horário do dia seguinte (REQ-DIST-014).
- Subtask 17.5: Envios além de 7 dias ficam `pending_capacity` com motivo visível e são reavaliados diariamente (REQ-DIST-008).
- Subtask 17.6: Intervalo 0: todos com T0; worker libera no máximo N uploads simultâneos por conta (padrão 1).
- Subtask 17.7: Fuso horário por conta (padrão `America/Sao_Paulo`).

## Task 18: Criação de envios e idempotência
Nível: 5
Status: -1

- Subtask 18.1: `request_key` única por lote gerada pelo formulário; duplo clique não cria segundo lote (REQ-DIST-011).
- Subtask 18.2: Um `publish_job` por par vídeo × conta, após validar: item `approved` com a conta aprovada, conta conectada e associada à operação.
- Subtask 18.3: Se já existe envio publicado ou ativo do mesmo `sha256` na mesma conta, criar como `skipped` com motivo visível (REQ-ACC-005).
- Subtask 18.4: Restrição única `(render_id, account_id)` no banco.
- Subtask 18.5: Alterar intervalo recalcula só envios `planned`; cancelar lote cancela `planned` e `pending_capacity`, sem tocar nos publicados.

## Task 19: Estados do envio, falhas e retries
Nível: 5
Status: -1

- Subtask 19.1: Máquina de estados do envio (seção 9.4): `planned`, `pending_capacity`, `uploading`, `scheduled_platform`, `processing`, `retry_wait`, `uncertain`, `published`, `failed`, `skipped`, `cancelled`.
- Subtask 19.2: Textos de interface por estado (REQ-DIST-012): planejado, pendente (motivo), enviando, agendado na plataforma, processando, nova tentativa às X, resultado incerto, publicado com link, falhou com motivo, ignorado com motivo, cancelado.
- Subtask 19.3: Erro temporário ou rate limit: `retry_wait` de 2, 10 e 30 minutos; depois `failed`.
- Subtask 19.4: Timeout após envio → `uncertain`; o worker chama `adapter.check()` antes de qualquer retry.
- Subtask 19.5: Se `check()` não for possível, o envio fica parado aguardando decisão manual e nunca é reenviado automaticamente (REQ-DIST-015).
- Subtask 19.6: Retry atua só no envio que falhou; sucessos do lote não são repetidos (REQ-DIST-010).

## Task 20: Dashboard e navegação
Nível: 3
Status: -1

- Subtask 20.1: Menu com 6 itens: Dashboard, Operações, Fila, Aprovação, Publicações, Contas.
- Subtask 20.2: Cards clicáveis que abrem a fila filtrada: operações ativas, execuções rodando, aguardando aprovação, planejados hoje, publicados hoje, falhas, contas com erro (REQ-UI-001).
- Subtask 20.3: Editor abre a partir da aprovação ou da fila, sem item próprio no menu.
- Subtask 20.4: Painel de erros alimentado pela tabela `events`.

## Task 21: Testes e critérios de aceitação
Nível: 5
Status: -1

- Subtask 21.1: Play com X gera execução rastreável (critério 2).
- Subtask 21.2: Mesmos registros aparecem na fila da operação e na fila geral (critério 3).
- Subtask 21.3: Duplicados, inválidos ou sem autorização não contam como elegíveis (critério 4).
- Subtask 21.4: Intervalo 0 libera tudo sem espaçamento, respeitando limites; intervalo positivo gera horários progressivos (critérios 6 e 7).
- Subtask 21.5: Marcar ou desmarcar "primeira imediata" muda o primeiro horário de cada conta (critério 8).
- Subtask 21.6: Várias contas geram uma tarefa por vídeo × conta (critério 9).
- Subtask 21.7: Falha numa plataforma não repete os sucessos nas outras (critério 10).
- Subtask 21.8: Com limite atingido, agenda o máximo e mantém o resto pendente com motivo (critério 11).
- Subtask 21.9: Repetir um pedido de distribuição não duplica publicações (critério 12).
- Subtask 21.10: Checklist final dos 12 critérios de aceitação marcado em CI.

## Task 22: Deploy e operação
Nível: 3
Status: -1

- Subtask 22.1: Compose de produção em 1 VPS: `web`, `worker`, `postgres`.
- Subtask 22.2: Backup automático do PostgreSQL.
- Subtask 22.3: Storage em disco local; migração para R2 quando necessário.
- Subtask 22.4: Health check da aplicação e do worker.
- Subtask 22.5: Política de retenção e limpeza de arquivos (não especificada na v2.1; ver Task 24).

## Task 23: Fase 4 — Expansão
Nível: 2
Status: -1

- Subtask 23.1: Adaptador TikTok (apps sem auditoria publicam só como privado ou rascunho).
- Subtask 23.2: Adaptador Instagram (conta profissional e limite diário via API).
- Subtask 23.3: Métricas de engajamento (views, likes, retenção).
- Subtask 23.4: Conectores de fonte adicionais.

## Task 24: Decisões em aberto
Nível: 4
Status: -1

- Subtask 24.1: Definir quais comunidades do Reddit têm autorização para as primeiras fontes.
- Subtask 24.2: Definir `daily_limit` inicial por conta (proposta: 3 por dia no YouTube até medir a cota real).
- Subtask 24.3: Decidir se a aprovação automática entra na Fase 2 e seus critérios (campo `approval.required` já existe).
- Subtask 24.4: Definir política de retenção e limpeza de arquivos.

---

## Fora desta versão (seção 17 da spec)

Não são tarefas agora: vários usuários com papéis, fair scheduling entre operações, alertas proativos, custo por vídeo, execução agendada para o futuro, timeline no editor, thumbnail personalizada, e política global de intervalo entre contas.
