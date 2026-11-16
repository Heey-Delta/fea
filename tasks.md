# Tasks — Ferramenta de Operações de Vídeo

Fontes:
- Artefato **"Especificação da Ferramenta — v2.1"** (https://claude.ai/artifact/GHvbjsWudPNWXgXHyUyEz5).
- `docs/editor-nivel-1.md` (editor automático, Nível 1, adaptado ao projeto).
- `docs/fluxo-operacao.md` (blocos Pesca, Edição, Postagem e canvas da operação).
- Wireframe navegável, 20 telas (https://claude.ai/artifact/1xSF1qABqYpySyFhNZYZHy). Cada tela traz as tasks que atende.

## Legenda

- **Nível** (atenção): 1 a 5, sendo 5 o maior.
- **Status**: `-1` = nada (não iniciada) · `0` = em trabalho · `1` = concluída.

## Mapa de fases

Blocos do produto (ver `docs/fluxo-operacao.md`): **Pesca** (Tasks 5 a 8), **Edição** (Tasks 9 a 18), **Postagem** (Tasks 19 a 24). Montados no canvas da operação (Task 4).

- **Base:** Tasks 1 a 3.
- **Fase 1 — Operação e coleta:** Tasks 4 a 8.
- **Fase 2 — Edição e aprovação:** Tasks 9 a 18 (módulo de redes e editor Nível 1).
- **Fase 3 — Distribuição:** Tasks 19 a 24 (YouTube Shorts primeiro).
- **Transversais:** Tasks 25 a 27.
- **Fase 4 — Expansão:** Task 28.
- **Decisões pendentes:** Task 29. As decisões da Task 29 precisam ser fechadas antes da Task 3.

---

## Task 1: Fundação do projeto
Nível: 5
Status: -1

- Subtask 1.1: Estrutura de pastas: `core/`, `networks/`, `app/`, `worker/`, `migrations/`, `storage/`, `tests/`, `docs/`.
- Subtask 1.2: Docker Compose de desenvolvimento (serviços `web`, `worker`, `postgres`).
- Subtask 1.3: Imagem com FFmpeg, ffprobe, Pillow e fontes instaladas. Validar com um comando de teste.
- Subtask 1.4: Configuração por variáveis de ambiente, incluindo a chave de criptografia dos tokens.
- Subtask 1.5: Aplicação FastAPI com Jinja2 + HTMX e layout base responsivo.
- Subtask 1.6: Ferramenta de migrações (a escolher) e migração inicial vazia.
- Subtask 1.7: Login do usuário único, sem papéis.
- Subtask 1.8: Logging estruturado que nunca exibe tokens ou segredos.

## Task 2: Banco de dados (14 tabelas)
Nível: 5
Status: -1

- Subtask 2.1: `operations` e `operation_configs` (config JSON versionada; inclui preset de edição e perfil de rede).
- Subtask 2.2: `accounts` e `operation_accounts` (muitos-para-muitos).
- Subtask 2.3: `sources` e `executions` (`execution_id`, `config_version_id`, snapshot).
- Subtask 2.4: `items` e `renders` (`preset_version_id`, `mask_version_id`, `input_file`, `output_file`, status, erro). Aprovação no item: `approved_render_id`, `approved_account_ids`.
- Subtask 2.5: `mask_assets` e `mask_versions` (arquivo, formato, largura, altura, `has_alpha`, checksum).
- Subtask 2.6: `batches` e `publish_jobs`, com restrição única `(render_id, account_id)`.
- Subtask 2.7: `jobs` com `idempotency_key` única e índices em `status` e `run_at`.
- Subtask 2.8: `events` como log de auditoria, de renderização (substitui `RENDER_LOGS`) e de alterações de preset e máscara.
- Subtask 2.9: Índices: `(source_id, external_id)`, `sha256`, `phash`.
- Subtask 2.10: Constraints de status conforme as máquinas de estado do item e do envio.

## Task 3: Fila de tarefas e workers
Nível: 5
Status: -1

- Subtask 3.1: Confirmar a decisão de fila (Task 29.1) antes de começar.
- Subtask 3.2: Fila isolada atrás de uma interface, para trocar a implementação sem mudar o motor.
- Subtask 3.3: Captura de tarefa com `FOR UPDATE SKIP LOCKED`, ordenando por prioridade e `run_at`.
- Subtask 3.4: Loops por tipo com concorrência: `collect` (2), `render` (1 por núcleo livre), `publish` (1 por conta), `scheduler_tick` (1).
- Subtask 3.5: Idempotência: `collect:{execution_id}`, `render:{item_id}:{config_version}`, `publish:{publish_job_id}`. Tarefa que reaparece detecta o efeito existente e termina.
- Subtask 3.6: Retries com `run_at`.
- Subtask 3.7: `scheduler_tick` a cada 1 minuto.
- Subtask 3.8: Worker não pega tarefas de execução pausada. Tarefas em andamento terminam.
- Subtask 3.9: Prioridade `alta`, `normal`, `baixa`, herdada por itens e tarefas.

## Task 4: Operações
Nível: 4
Status: -1

- Subtask 4.1: CRUD de operação (nome, status).
- Subtask 4.2: Configuração JSON versionada. Cada salvamento cria versão e as anteriores nunca mudam (REQ-UI-003).
- Subtask 4.3: Estados `draft`, `active`, `paused`, `archived`.
- Subtask 4.4: `paused` não aceita Play novo, e envios planejados ficam em espera. `archived` é somente leitura.
- Subtask 4.5: Formulário único com seções, sem assistente de várias etapas.
- Subtask 4.6: Tela de detalhe com abas: Visão geral, Configuração, Fontes, Contas, Execuções, Histórico de versões.
- Subtask 4.7: Lista de operações com botão Play em cada linha.
- Subtask 4.8: Teste: duas operações com configurações diferentes rodando nos mesmos motores (critério 1 da v2.1).
- Subtask 4.9: Canvas de criação: blocos como cartões, com portas de entrada e saída. Paleta: Fonte, Pesca, Edição, Aprovação, Postagem, Rede, Conta.
- Subtask 4.10: Ligar saída a entrada cria aresta. Ligações fora da tabela de tipos de porta são recusadas com motivo.
- Subtask 4.11: Clicar no bloco abre painel de configuração em formulário, do lado direito. O canvas não edita vídeo.
- Subtask 4.12: Validação antes de ativar: Fonte → Pesca → Edição → Aprovação → Postagem; uma Rede ligada a Edição e Postagem; ao menos uma Conta na Postagem; sem ciclos. Erros marcados no bloco.
- Subtask 4.13: Fonte sem `permission_note` gera aviso, não bloqueia. Rascunho pode ter erros, operação ativa não.
- Subtask 4.14: Grafo (nós, arestas e configs) salvo como JSON versionado em `operation_configs`. Cada execução guarda snapshot.
- Subtask 4.15: Motor executa o grafo chamando o módulo de cada tipo de bloco. Tipo novo de bloco não exige mudar o canvas.
- Subtask 4.16: Operação arquivada abre o canvas em somente leitura. Opção de duplicar para criar nova versão do fluxo.

## Task 5: Fontes e conectores
Nível: 4
Status: -1

- Subtask 5.1: Cadastro de fonte por operação (`type`, `reference`, `permission_note`, `status`, `cursor`, `last_error`).
- Subtask 5.2: `permission_note` obrigatório. Sem ele, os itens entram como `pending_permission` (REQ-UI-004).
- Subtask 5.3: Interface `SourceConnector` (`fetch`, `download`) e modelo `RawItem`.
- Subtask 5.4: Conector de upload manual.
- Subtask 5.5: Conector Reddit pela API oficial, só em comunidades com autorização registrada.
- Subtask 5.6: Erro temporário: até 3 tentativas com espera crescente.
- Subtask 5.7: Credencial inválida ou fonte removida: `status=error`, aparece no dashboard, e a execução segue com as outras fontes.
- Subtask 5.8: Interface `search(tags, cursor)` além de `fetch`. Conector declara se suporta busca. Reddit pesquisa por tags e heat tags. Upload manual não pesquisa: tags viram só filtro.
- Subtask 5.9: Cada Fonte é um bloco no canvas, com `permission_note` e tipo de conector.

## Task 6: Execução (Play)
Nível: 5
Status: -1

- Subtask 6.1: Tela do Play com quantidade X, orçamento de busca, fontes (todas marcadas), critério e prioridade.
- Subtask 6.2: Criar `executions` com `config_version_id` congelada, X, orçamento e `status=running`.
- Subtask 6.3: Tarefa `collect` para ao atingir X elegíveis, ao estourar o orçamento ou ao esgotar as fontes.
- Subtask 6.4: Critério "mais recentes" (padrão).
- Subtask 6.5: Critério "priorizar heat tags": examina até `min(orçamento, 3 × X)` e seleciona os X de maior score. O restante fica `eligible` com motivo "reserva".
- Subtask 6.6: "Processar selecionados" para processar os itens reserva depois.
- Subtask 6.7: Fechamento: `completed` se chegou a X; `partial` com `shortfall_reason` caso contrário.
- Subtask 6.8: Contadores por `COUNT` sobre `items` (examinados, duplicados, rejeitados, pendentes de permissão, elegíveis, renderizados, aguardando aprovação, com erro).
- Subtask 6.9: Controles: pausar, retomar, cancelar (não apaga registros), reexecutar como novo Play com novo `execution_id`.
- Subtask 6.10: Execuções simultâneas da mesma operação são permitidas.
- Subtask 6.11: Bloco Pesca do grafo fornece tags, heat tags, palavras bloqueadas, X, orçamento, critério, duração e mídia aceita.
- Subtask 6.12: Pesca e Edição rodam sem ação do usuário. Postagem só roda por ação explícita (Task 21).

## Task 7: Itens, validação, deduplicação e classificação
Nível: 5
Status: -1

- Subtask 7.1: Máquina de estados do item (tabela da seção 6.1 da v2.1).
- Subtask 7.2: Checagem de formato, duração (`max_duration_s`), palavra bloqueada e nicho → `rejected`.
- Subtask 7.3: Deduplicação em ordem:
  - Subtask 7.3.1: Mesmo item externo `(source_id, external_id)`, escopo da fonte.
  - Subtask 7.3.2: Mesmo arquivo por `sha256`, escopo global.
  - Subtask 7.3.3: Imagem parecida por `phash` com distância ≤ 6, escopo global.
- Subtask 7.4: pHash de vídeo sobre 3 quadros (10%, 50%, 90% da duração).
- Subtask 7.5: Duplicado de outra operação recebe `duplicate` com `duplicate_of`.
- Subtask 7.6: Classificação: score = tags (1) + heat tags (2) no texto ou título original. Score 0 com tags configuradas → `rejected`.
- Subtask 7.7: Permissão: o item herda o `permission_note` da fonte. Sem permissão → `pending_permission`, com liberar ou rejeitar em lote na fila.

## Task 8: Filas
Nível: 4
Status: -1

- Subtask 8.1: Fila geral com colunas: item, operação, execução, etapa/estado, prioridade, score, data, erro, ação.
- Subtask 8.2: Fila da operação é a mesma tela com filtro `operation_id` (REQ-QUEUE-003).
- Subtask 8.3: Filtros por operação e por etapa.
- Subtask 8.4: Estados visíveis: encontrado, em validação, pendente de autorização, elegível, em edição, em correção, aguardando aprovação, aprovado, rejeitado, agendado, publicado, falha (REQ-QUEUE-005).
- Subtask 8.5: Seleção em lote com resumo antes de confirmar (REQ-UI-005).
- Subtask 8.6: Ordenação por prioridade da execução, depois por score.

---

## Task 9: Módulo de redes sociais (perfis)
Nível: 5
Status: -1

- Subtask 9.1: Interface `NetworkProfile`: id, nome, saída padrão, restrições, regras de QC, limites de metadados, capacidades, adaptador de publicação.
- Subtask 9.2: Registro de perfis carregado pelo core. Cada operação escolhe um perfil.
- Subtask 9.3: Validação do preset contra o perfil ao salvar. Preset fora das restrições é recusado.
- Subtask 9.4: O core não importa código de rede. Os perfis dependem do core, nunca o contrário (teste de arquitetura).
- Subtask 9.5: Perfil `youtube_shorts`: 9:16, 1080 × 1920, MP4, H.264, AAC, 30 FPS, yuv420p, vertical.
- Subtask 9.6: Confirmar na documentação atual do YouTube a duração máxima, o limite de título e de descrição antes de fixar os valores.
- Subtask 9.7: Deixar a estrutura pronta para `tiktok` e `instagram_reels`, sem implementar.

## Task 10: Motor de edição — pipeline e análise
Nível: 5
Status: -1

- Subtask 10.1: Recebimento: identifica operação, item e preset.
- Subtask 10.2: Análise com ffprobe: resolução, proporção, FPS, duração, codecs, áudio, integridade. Persistir o resultado.
- Subtask 10.3: Snapshot do preset (versão e perfil de rede) gravado na execução e congelado.
- Subtask 10.4: Orquestração das etapas 4 a 12 da `docs/editor-nivel-1.md`, com status por etapa e registro em `events`.
- Subtask 10.5: Falha em um vídeo não interrompe os demais.

## Task 11: Padronização e enquadramento
Nível: 5
Status: -1

- Subtask 11.1: Conversão para resolução, FPS, pixel format e codecs do preset.
- Subtask 11.2: Modo A (preencher): cobre a área e corta o excesso. Posição do corte configurável (centro, topo, base).
- Subtask 11.3: Modo B (ajustar): redimensiona proporcionalmente e centraliza. Sobras com cor de fundo configurada.
- Subtask 11.4: Modo C (fundo desfocado): camada de fundo ampliada e desfocada, com o vídeo original centralizado por cima. Intensidade do desfoque configurável.
- Subtask 11.5: Testes com horizontal, vertical e quadrado (critérios 1 a 4 do editor).
- Subtask 11.6: Saída MP4 H.264 e AAC.

## Task 12: Máscaras PNG
Nível: 4
Status: -1

- Subtask 12.1: Importação e armazenamento em `mask_assets` e `mask_versions`, com checksum.
- Subtask 12.2: Validação: integridade, PNG, dimensões, canal alfa, compatibilidade e proporção. Corrompido bloqueia. Incompatível gera aviso antes do uso.
- Subtask 12.3: Visualização do PNG com resolução, proporção e transparência.
- Subtask 12.4: Associação à operação, substituição e histórico de versões.
- Subtask 12.5: Posicionamento: posição horizontal e vertical, largura, altura, escala, alinhamento. Padrão: 0, 0, 100%, 100%.
- Subtask 12.6: Opacidade (padrão 100%).
- Subtask 12.7: Sobreposição em camada superior ao vídeo, sem reconstruir o vídeo.
- Subtask 12.8: Cada render guarda `mask_version_id`. Alteração de máscara não modifica renders antigos.

## Task 13: Textos e elementos gráficos
Nível: 4
Status: -1

- Subtask 13.1: Texto desenhado em PNG pelo Pillow (quebra de linha, contorno, sombra, alinhamento) e sobreposto pelo FFmpeg.
- Subtask 13.2: Texto fixo e texto variável, com `{titulo}` vindo dos metadados.
- Subtask 13.3: Posições predefinidas (superior, inferior, central) e personalizada. Margens de segurança do preset.
- Subtask 13.4: Largura e altura máximas. Estourar gera aviso.
- Subtask 13.5: Logotipo, marca d'água e imagens adicionais (PNG) com posição, escala e opacidade.
- Subtask 13.6: Sem detecção de áreas livres. Posições são sempre regras fixas.

## Task 14: Áudio
Nível: 4
Status: -1

- Subtask 14.1: Preservar, remover ou substituir.
- Subtask 14.2: Volume do áudio original ou do substituto.
- Subtask 14.3: Normalização de loudness.
- Subtask 14.4: Fade-in e fade-out em segundos.
- Subtask 14.5: Saída AAC quando há faixa de áudio.
- Subtask 14.6: Permissão de uso do áudio substituto registrada no preset.
- Subtask 14.7: Aviso quando o preset exige áudio e o original não tem faixa. Bloqueio só se marcado como obrigatório.

## Task 15: Presets e versionamento
Nível: 5
Status: -1

- Subtask 15.1: Preset dentro do JSON versionado da operação: identificação, perfil, vídeo, máscara, textos, elementos, áudio, exportação.
- Subtask 15.2: Formulário de configuração em seções, sem timeline e sem prévia editável.
- Subtask 15.3: Ações: salvar, atualizar (gera versão), duplicar, ativar, consultar histórico.
- Subtask 15.4: "Testar preset": render de amostra com vídeo de exemplo e relatório de QC. Resultado não editável.
- Subtask 15.5: Execução iniciada guarda snapshot. Alterar preset depois não afeta essa execução.
- Subtask 15.6: Alterações de preset registradas em `events`.

## Task 16: Títulos e metadados
Nível: 3
Status: -1

- Subtask 16.1: Cadeia de Markov de ordem 2 treinada no corpus; geração de N candidatos.
- Subtask 16.2: Filtros: `max_chars`, `blocked_words`, sem cópia exata de linha do corpus, sem repetir títulos já usados na operação.
- Subtask 16.3: Primeiro candidato válido. Se nenhum passar, `fallback_templates` aleatório. Registrar `title_method`.
- Subtask 16.4: `visual_title` (dentro do vídeo) e `publication_title` (plataforma), editáveis separadamente na aprovação.
- Subtask 16.5: Alterar `visual_title` exige novo render. Alterar `publication_title` ou descrição não exige.
- Subtask 16.6: Descrição a partir de `description_template`.
- Subtask 16.7: Hashtags por plataforma via `metadata.hashtags_by_platform`, com fallback para `hashtags`.

## Task 17: Controle de qualidade (QC)
Nível: 5
Status: -1

- Subtask 17.1: Verificações: arquivo existe e abre, não está corrompido, resolução, proporção, FPS, codec, formato, duração, áudio conforme configuração, máscara aplicada, arquivo armazenado.
- Subtask 17.2: Classificação em impeditivo (bloqueia) e aviso (não bloqueia), conforme a seção 13.2 de `docs/editor-nivel-1.md`.
- Subtask 17.3: Falha impeditiva: registrar erro, marcar tarefa como falha, preservar original, permitir reprocessamento, não encaminhar.
- Subtask 17.4: Avisos não impedem o encaminhamento, mas aparecem na fila e no relatório.
- Subtask 17.5: Relatório de validação salvo por render.
- Subtask 17.6: Retry automático só para erro de processo, com limite configurável (proposta: 2).
- Subtask 17.7: Regras específicas do perfil de rede aplicadas no QC (ligado à Task 9.1).

## Task 18: Aprovação
Nível: 5
Status: -1

- Subtask 18.1: Tela com player do render, origem, permissão, resultado do QC, títulos e descrição editáveis, contas autorizadas (REQ-UI-007).
- Subtask 18.2: Botões: aprovar, rejeitar, nova versão. Nova versão é um novo render com o preset atual, não uma edição manual.
- Subtask 18.3: Aprovação vale para um render exato e para as contas autorizadas (REQ-APP-004).
- Subtask 18.4: Gerar render novo zera `approved_render_id` e `approved_account_ids`.
- Subtask 18.5: Aprovação em lote em grade, com resumo antes de confirmar. Bloqueia itens com `needs_fix` ou sem permissão.
- Subtask 18.6: Se a operação exige aprovação, preparar não publica (REQ-APP-001).
- Subtask 18.7: Aprovar um conjunto e distribuir só os selecionados (critério 5 da v2.1).

---

## Task 19: Contas
Nível: 5
Status: -1

- Subtask 19.1: Tabela `accounts` e vínculo com operações via `operation_accounts` (REQ-ACC-001).
- Subtask 19.2: Conexão por OAuth oficial.
- Subtask 19.3: Token criptografado no banco, com chave em variável de ambiente. Nunca vai ao frontend nem aparece em log.
- Subtask 19.4: `daily_limit` configurado manualmente por conta.
- Subtask 19.5: Tela de contas: conectar, testar, pausar, revogar, ver operações associadas e envios recentes (REQ-UI-009).
- Subtask 19.6: Token inválido → conta em `status=error` e envios dela em `pending_capacity` ("reconectar conta"). Outras contas não são afetadas.

## Task 20: Adaptador de plataforma — YouTube Shorts
Nível: 5
Status: -1

- Subtask 20.1: Interface `PlatformAdapter` (`publish`, `check`, `capabilities`: `direct_publish`, `native_schedule`, `drafts_only`).
- Subtask 20.2: Adaptador `youtube_shorts`: OAuth, upload e controle da cota diária.
- Subtask 20.3: Confirmar na documentação atual da API a cota, o limite de uploads e o formato exigido antes de implementar.
- Subtask 20.4: Usar agendamento nativo só quando o adaptador suportar.
- Subtask 20.5: TikTok e Instagram Reels ficam para a Task 28.

## Task 21: Nova publicação
Nível: 5
Status: -1

- Subtask 21.1: Tela única com: lista de vídeos aprovados (checkbox e "selecionar todos"), contas da operação, intervalo em minutos, "Primeira publicação imediata", início (data e hora, aparece se a caixa estiver desmarcada).
- Subtask 21.2: Metadados por plataforma ou conta, opcionais e recolhidos por padrão: `title_override`, `description_override`. Confirmação registrada em `events`.
- Subtask 21.3: Prévia da agenda por conta antes de confirmar.
- Subtask 21.4: Botão Confirmar.
- Subtask 21.5: Lista de lotes e lista de envios com os estados da Task 24.
- Subtask 21.6: Bloco Postagem do canvas: entrada são renders aprovados; configs são contas (arestas), intervalo, primeira imediata, início, janela, título, descrição e tags por plataforma.
- Subtask 21.7: Bloco Aprovação entre Edição e Postagem, com `approval.required`.

## Task 22: Cálculo de horários
Nível: 5
Status: -1

- Subtask 22.1: Definição de T0: se primeira imediata → agora; senão, se há início → início; senão → agora + intervalo (REQ-DIST-013). Com intervalo 0 → agora.
- Subtask 22.2: Horário n = T0 + (n − 1) × intervalo, por conta.
- Subtask 22.3: Janela de publicação (`window`): horário fora da janela vai para o início da próxima.
- Subtask 22.4: Limite diário: ao atingir `daily_limit`, o envio vai para o primeiro horário do dia seguinte (REQ-DIST-014).
- Subtask 22.5: Envios além de 7 dias ficam `pending_capacity` com motivo visível e são reavaliados diariamente (REQ-DIST-008).
- Subtask 22.6: Intervalo 0: todos com T0. O worker libera no máximo N uploads simultâneos por conta (padrão 1).
- Subtask 22.7: Fuso horário por conta (padrão `America/Sao_Paulo`).

## Task 23: Criação de envios e idempotência
Nível: 5
Status: -1

- Subtask 23.1: `request_key` única por lote, gerada pelo formulário. Duplo clique não cria segundo lote (REQ-DIST-011).
- Subtask 23.2: Um `publish_job` por par vídeo × conta, após validar: item `approved` com a conta aprovada, conta conectada e associada à operação.
- Subtask 23.3: Se já existe envio publicado ou ativo do mesmo `sha256` na mesma conta, criar como `skipped` com motivo visível (REQ-ACC-005).
- Subtask 23.4: Restrição única `(render_id, account_id)` no banco.
- Subtask 23.5: Alterar intervalo recalcula só envios `planned`. Cancelar lote cancela `planned` e `pending_capacity`, sem tocar nos publicados.

## Task 24: Estados do envio, falhas e retries
Nível: 5
Status: -1

- Subtask 24.1: Máquina de estados do envio (seção 9.4 da v2.1): `planned`, `pending_capacity`, `uploading`, `scheduled_platform`, `processing`, `retry_wait`, `uncertain`, `published`, `failed`, `skipped`, `cancelled`.
- Subtask 24.2: Textos de interface por estado (REQ-DIST-012).
- Subtask 24.3: Erro temporário ou rate limit: `retry_wait` de 2, 10 e 30 minutos; depois `failed`.
- Subtask 24.4: Timeout após envio → `uncertain`. O worker chama `adapter.check()` antes de qualquer retry.
- Subtask 24.5: Se `check()` não for possível, o envio fica parado aguardando decisão manual e nunca é reenviado automaticamente (REQ-DIST-015).
- Subtask 24.6: Retry atua só no envio que falhou. Sucessos do lote não são repetidos (REQ-DIST-010).

---

## Task 25: Dashboard e navegação
Nível: 3
Status: -1

- Subtask 25.1: Menu com 6 itens: Dashboard, Operações, Fila, Aprovação, Publicações, Contas. Não há item de editor.
- Subtask 25.2: Cards clicáveis que abrem a fila filtrada: operações ativas, execuções rodando, aguardando aprovação, planejados hoje, publicados hoje, falhas, contas com erro (REQ-UI-001).
- Subtask 25.3: Painel de erros alimentado por `events`.
- Subtask 25.4: Configuração de preset e máscara acessível pela operação (aba Configuração), não pelo menu.

## Task 26: Testes e critérios de aceitação
Nível: 5
Status: -1

- Subtask 26.1: Critérios da v2.1 (12): Play gera execução rastreável, filas consistentes, dedup e permissão não contam como elegíveis, aprovação em lote, intervalo 0 e positivo, primeira imediata, uma tarefa por vídeo × conta, falha isolada entre plataformas, limite diário com `pending_capacity`, idempotência do pedido.
- Subtask 26.2: Critérios do editor Nível 1 (20), da seção 18 de `docs/editor-nivel-1.md`.
- Subtask 26.3: Teste de arquitetura: o core não importa `networks/`.
- Subtask 26.4: Teste de reprodutibilidade: mesmo preset e mesmo original geram o mesmo resultado técnico (resolução, FPS, codecs, duração).
- Subtask 26.5: Checklist dos critérios marcado em CI.

## Task 27: Deploy e operação
Nível: 3
Status: -1

- Subtask 27.1: Compose de produção em 1 VPS: `web`, `worker`, `postgres`.
- Subtask 27.2: Backup automático do PostgreSQL.
- Subtask 27.3: Storage em disco local, com adaptador para R2 (Task 29.3).
- Subtask 27.4: Health check da aplicação e do worker.
- Subtask 27.5: Política de retenção e limpeza de arquivos (Task 29.5).

## Task 28: Fase 4 — Expansão
Nível: 2
Status: -1

- Subtask 28.1: Perfil e adaptador TikTok. Apps sem auditoria publicam só como privado ou rascunho.
- Subtask 28.2: Perfil e adaptador Instagram Reels. Exige conta profissional e tem limite diário via API.
- Subtask 28.3: Métricas de engajamento (views, likes, retenção).
- Subtask 28.4: Conectores de fonte adicionais.

## Task 29: Decisões em aberto
Nível: 4
Status: -1

- Subtask 29.1: **Fila de tarefas**: Postgres com `FOR UPDATE SKIP LOCKED` (recomendado, da v2.1) ou Redis + Celery (da especificação do editor). Decidir antes da Task 3.
- Subtask 29.2: **Tabelas**: confirmar 14 tabelas (v2.1 + `mask_assets` e `mask_versions`; presets em `operation_configs`; logs de render em `events`).
- Subtask 29.3: **Armazenamento**: disco local agora com adaptador R2, ou R2 desde o início.
- Subtask 29.4: **Editor**: confirmar que o REQ-UI-006 da v2.1 é removido (sem editor). Atualizar o artefato da v2.1 para refletir isso.
- Subtask 29.5: **Retenção de arquivos**: definir política de limpeza.
- Subtask 29.6: **YouTube Shorts**: confirmar duração máxima, limites de título e descrição, e cota.
- Subtask 29.7: **Tentativas automáticas do render**: confirmar limite (proposta: 2).
- Subtask 29.8: **Áudio substituto**: definir como registrar a permissão de uso.
- Subtask 29.9: **Comunidades do Reddit** autorizadas para as primeiras fontes.
- Subtask 29.10: **`daily_limit` inicial** por conta (proposta: 3 por dia no YouTube até medir a cota real).
- Subtask 29.11: **Aprovação automática**: entra na Fase 2 ou depois, e com quais critérios (campo `approval.required` já existe).
- Subtask 29.12: **Canvas e "sem editor"**: confirmar que o canvas só configura o fluxo (blocos e ligações) e não edita vídeo. Proposta: sim.
- Subtask 29.13: **Blocos de topo**: confirmar Aprovação e Rede como blocos próprios, e uma Rede por operação (`docs/fluxo-operacao.md`, seção 6).
- Subtask 29.14: **Busca por tags**: confirmar que conectores declaram `search(tags, cursor)` além de `fetch`.

---

## Fora desta versão

Conforme seção 17 da v2.1, e sem recursos inteligentes no editor Nível 1: vários usuários com papéis, fair scheduling entre operações, alertas proativos, custo por vídeo, execução agendada para o futuro, timeline e editor manual, thumbnail personalizada, política global de intervalo entre contas, rastreamento de rostos e objetos, legendas automáticas, cortes inteligentes, construtor de máscaras.
