# Tasks — Ferramenta de Operações de Vídeo

Fontes:
- Artefato **"Especificação da Ferramenta — v2.1"** (https://claude.ai/artifact/GHvbjsWudPNWXgXHyUyEz5). A seção 18 tem as decisões mais recentes.
- `docs/editor-nivel-1.md` (editor automático, Nível 1, adaptado ao projeto).
- `docs/fluxo-operacao.md` (blocos Pesca, Edição, Postagem e canvas da operação).
- Wireframe navegável, 20 telas (https://claude.ai/artifact/1xSF1qABqYpySyFhNZYZHy). Cada tela traz as tasks que atende.

## Legenda

- **Nível** (atenção): 1 a 5, sendo 5 o maior.
- **Status**: `-1` = nada (não iniciada) · `0` = em trabalho · `1` = concluída.

## Arquitetura adotada

| Parte | Onde | O que roda |
|---|---|---|
| Interface | Vercel (FastAPI + Jinja2 + HTMX) | Telas, canvas, aprovação, retorno do OAuth |
| Banco | Neon (Postgres, via Vercel Marketplace) | Dados, versões e fila de tarefas |
| Processamento | VPS (Oracle Always Free) com Docker | Buscador, Editor, Postador e Limpeza |
| Arquivos | Cloudflare R2 | Originais, renders e máscaras |

Fluxo: Buscador → fila de pesca → Editor → fila de editados → (aprovação manual ou automática) → Postador → fila de exclusão → Limpeza (X minutos após a publicação, padrão 30).

## Mapa de fases

Blocos do produto (ver `docs/fluxo-operacao.md`): **Pesca** (Tasks 5 a 8), **Edição** (Tasks 9 a 18), **Postagem** (Tasks 19 a 24). Montados no canvas da operação (Task 4).

- **Base:** Tasks 1 a 3.
- **Fase 1 — Operação e coleta:** Tasks 4 a 8.
- **Fase 2 — Edição e aprovação:** Tasks 9 a 18 (módulo de redes e editor Nível 1).
- **Fase 3 — Distribuição:** Tasks 19 a 24 (YouTube Shorts primeiro).
- **Transversais:** Tasks 25 a 27.
- **Fase 4 — Expansão:** Task 28.
- **Decisões:** Task 29.

---

## Task 1: Fundação do projeto
Nível: 5
Status: 1

- Subtask 1.1: Estrutura de pastas: `core/` (motor genérico), `networks/` (perfis por rede), `web/` (interface na Vercel), `worker/` (processos da VPS), `migrations/`, `tests/`, `docs/`.
- Subtask 1.2: `pyproject.toml` com as dependências e o ambiente gerenciado por `uv`.
- Subtask 1.3: Configuração por variáveis de ambiente (`.env.example`), incluindo a chave de criptografia dos tokens, que precisa existir na Vercel e na VPS.
- Subtask 1.4: Interface FastAPI com Jinja2 + HTMX, layout base e entrada `app.py` para a Vercel (`vercel.json`).
- Subtask 1.5: Login só com OAuth do GitHub, liberado para a conta em `GITHUB_ALLOWED_ID` (decidido). Sessão assinada.
- Subtask 1.6: Logging estruturado que nunca exibe tokens ou segredos.
- Subtask 1.7: Alembic configurado, com migração inicial vazia.
- Subtask 1.8: Imagem Docker do worker com FFmpeg, ffprobe, Pillow e fontes. Docker Compose de desenvolvimento com Postgres local, interface e worker. A construção da imagem é verificada pelo CI (Docker indisponível na sessão em que foi feita).
- Subtask 1.9: Healthcheck da interface (`/health`) e verificação de FFmpeg no worker.
- Subtask 1.10: CI no GitHub Actions (ruff + pytest) e README com instruções de execução.

## Task 2: Banco de dados (14 tabelas)
Nível: 5
Status: 1

- Subtask 2.1: `operations` e `operation_configs` (config JSON versionada; inclui grafo do canvas, preset, perfil de rede, modo automático, estoque e tempo de exclusão).
- Subtask 2.2: `accounts` e `operation_accounts` (muitos-para-muitos).
- Subtask 2.3: `sources` e `executions` (`execution_id`, `config_version_id`, snapshot).
- Subtask 2.4: `items` e `renders` (`preset_version_id`, `mask_version_id`, `input_file`, `output_file`, status, erro). Aprovação no item: `approved_render_id`, `approved_account_ids`, `approved_by` (manual ou automática).
- Subtask 2.5: `mask_assets` e `mask_versions` (arquivo, formato, largura, altura, `has_alpha`, checksum).
- Subtask 2.6: `batches` e `publish_jobs`, com restrição única `(render_id, account_id)`.
- Subtask 2.7: `jobs` com `idempotency_key` única e índices em `status`, `type` e `run_at`.
- Subtask 2.8: `events` como log de auditoria, de renderização e de alterações de preset e máscara.
- Subtask 2.9: Índices: `(source_id, external_id)`, `sha256`, `phash`.
- Subtask 2.10: Constraints de status conforme as máquinas de estado do item e do envio.
- Subtask 2.11: Campos de retenção: `files_deleted_at` em items e renders, e `delete_after` calculado a partir da última publicação.

## Task 3: Fila de tarefas e workers
Nível: 5
Status: 1

- Subtask 3.1: Fila no Postgres (decidido): tabela `jobs` atrás de uma interface, para trocar a implementação sem mudar o motor.
- Subtask 3.2: Captura de tarefa com `FOR UPDATE SKIP LOCKED`, ordenando por prioridade e `run_at`.
- Subtask 3.3: Quatro processos: Buscador (`collect`), Editor (`render`), Postador (`publish` + `scheduler_tick`) e Limpeza (`cleanup`).
- Subtask 3.4: Concorrência configurável (`WORKER_CONCURRENCY`): Buscador 2, Editor 1, Postador 2, Limpeza 1. O limite de 1 upload por conta é aplicado no handler de publicação (Task 24).
- Subtask 3.5: Idempotência: `collect:{execution_id}`, `render:{item_id}:{config_version}`, `publish:{publish_job_id}`, `cleanup:{item_id}`. Tarefa que reaparece detecta o efeito existente e termina.
- Subtask 3.6: Retries com `run_at` e espera crescente.
- Subtask 3.7: Espera sem gastar o banco: LISTEN/NOTIFY quando possível, e consulta em intervalos crescentes com a fila vazia (limite de horas do Neon gratuito).
- Subtask 3.8: Worker não pega tarefas de execução pausada. Tarefas em andamento terminam.
- Subtask 3.9: Prioridade `alta`, `normal`, `baixa`, herdada por itens e tarefas.
- Subtask 3.10: Falha num worker não para os outros; cada fila guarda o que não foi processado.

## Task 4: Operações e canvas
Nível: 4
Status: 1

- Subtask 4.1: CRUD de operação (nome, status).
- Subtask 4.2: Configuração JSON versionada. Cada salvamento cria versão e as anteriores nunca mudam (REQ-UI-003).
- Subtask 4.3: Estados `draft`, `active`, `paused`, `archived`.
- Subtask 4.4: `paused` não aceita Play novo, e envios planejados ficam em espera. `archived` é somente leitura.
- Subtask 4.5: Tela de detalhe com abas: Visão geral, Configuração, Fontes, Contas, Execuções, Histórico de versões.
- Subtask 4.6: Lista de operações com botão Play em cada linha.
- Subtask 4.7: Teste: duas operações com configurações diferentes rodando nos mesmos motores (critério 1 da v2.1).
- Subtask 4.8: Canvas de criação com Drawflow (decidido): blocos Fonte, Pesca, Edição, Aprovação, Postagem, Rede e Conta, com portas de entrada e saída. O canvas só configura o fluxo; não edita vídeo (decidido).
- Subtask 4.9: Ligações fora da tabela de tipos de porta são recusadas com motivo.
- Subtask 4.10: Clicar no bloco abre o painel de configuração do lado direito. Por enquanto em JSON; os formulários de cada bloco chegam com as Tasks 6, 15 e 21.
- Subtask 4.11: Validação antes de ativar: Fonte → Pesca → Edição → Aprovação → Postagem; uma Rede ligada a Edição e Postagem; ao menos uma Conta; sem ciclos.
- Subtask 4.12: Grafo (nós, arestas e configs) salvo como JSON versionado em `operation_configs`. Cada execução guarda snapshot.
- Subtask 4.13: Operação arquivada abre o canvas em somente leitura, com opção de duplicar.

## Task 5: Fontes e conectores (Buscador)
Nível: 4
Status: 0

- Subtask 5.1: Cadastro de fonte por operação (`type`, `reference`, `permission_note`, `status`, `cursor`, `last_error`).
- Subtask 5.2: `permission_note` obrigatório. Sem ele, os itens entram como `pending_permission` (REQ-UI-004).
- Subtask 5.3: Interface `SourceConnector` (`fetch`, `search(tags, cursor)`, `download`) e modelo `RawItem`.
- Subtask 5.4: Conector de upload manual (envio direto do navegador ao R2 por URL assinada).
- Subtask 5.5: Conector Reddit pela API oficial, só em comunidades com autorização registrada. Vídeo e áudio vêm separados e o FFmpeg junta.
- Subtask 5.6: Erro temporário: até 3 tentativas com espera crescente.
- Subtask 5.7: Credencial inválida ou fonte removida: `status=error`, aparece no dashboard, e a execução segue com as outras fontes.
- Subtask 5.8: Vários Buscadores por operação: cada bloco Fonte é um Buscador próprio, todos soltando na mesma fila de pesca (expansão; MVP só Reddit).

## Task 6: Execução (Play), modo automático e estoque
Nível: 5
Status: -1

- Subtask 6.1: Tela do Play com quantidade X, orçamento de busca, fontes, critério e prioridade.
- Subtask 6.2: Criar `executions` com `config_version_id` congelada, X, orçamento e `status=running`.
- Subtask 6.3: Tarefa `collect` para ao atingir X elegíveis, ao estourar o orçamento ou ao esgotar as fontes.
- Subtask 6.4: Critérios "mais recentes" (padrão) e "priorizar heat tags" (examina até `min(orçamento, 3 × X)`; o resto vira "reserva").
- Subtask 6.5: Fechamento: `completed` se chegou a X; `partial` com `shortfall_reason` caso contrário.
- Subtask 6.6: Contadores por `COUNT` sobre `items`.
- Subtask 6.7: Controles: pausar, retomar, cancelar (não apaga registros), reexecutar como novo Play.
- Subtask 6.8: Play diário agendado: horário configurado na operação dispara o Buscador sozinho.
- Subtask 6.9: Estoque com reposição automática: o Buscador roda quando os vídeos prontos caem abaixo do mínimo configurado (recomendado 3 a 7 dias de postagem).

## Task 7: Itens, validação, deduplicação e classificação
Nível: 5
Status: -1

- Subtask 7.1: Máquina de estados do item (tabela da seção 6.1 da v2.1).
- Subtask 7.2: Checagem de formato, duração (`max_duration_s`), palavra bloqueada e nicho → `rejected`.
- Subtask 7.3: Deduplicação em ordem:
  - Subtask 7.3.1: Mesmo item externo `(source_id, external_id)`, escopo da fonte.
  - Subtask 7.3.2: Mesmo arquivo por `sha256`, escopo global.
  - Subtask 7.3.3: Imagem parecida por `phash` com distância ≤ 6, escopo global, sobre 3 quadros (10%, 50%, 90%).
- Subtask 7.4: Duplicado de outra operação recebe `duplicate` com `duplicate_of`.
- Subtask 7.5: Classificação: score = tags (1) + heat tags (2). Score 0 com tags configuradas → `rejected`.
- Subtask 7.6: Permissão: o item herda o `permission_note` da fonte. Sem permissão → `pending_permission`.
- Subtask 7.7: Detecção de marca d'água de terceiro (logotipo de outras redes e texto do @ na imagem) → `rejected` com motivo "marca d'água de terceiro". Nunca remover a marca.

## Task 8: Filas
Nível: 4
Status: -1

- Subtask 8.1: Fila geral com colunas: item, operação, execução, etapa/estado, prioridade, score, data, erro, ação.
- Subtask 8.2: Fila da operação é a mesma tela com filtro `operation_id` (REQ-QUEUE-003).
- Subtask 8.3: Filtros por operação e por etapa (pesca, editados, exclusão e estados da REQ-QUEUE-005).
- Subtask 8.4: Seleção em lote com resumo antes de confirmar (REQ-UI-005).
- Subtask 8.5: Ordenação por prioridade da execução, depois por score.

---

## Task 9: Módulo de redes sociais (perfis)
Nível: 5
Status: -1

- Subtask 9.1: Interface `NetworkProfile`: saída padrão, restrições, regras de QC, limites de metadados, capacidades, adaptador.
- Subtask 9.2: Registro de perfis carregado pelo core. Cada operação escolhe um perfil.
- Subtask 9.3: Validação do preset contra o perfil ao salvar.
- Subtask 9.4: O core não importa código de rede (teste de arquitetura).
- Subtask 9.5: Perfil `youtube_shorts`: 9:16, 1080 × 1920, MP4, H.264, AAC, 30 FPS, yuv420p, até 3 minutos.
- Subtask 9.6: Confirmar no console do Google Cloud a cota e os limites de título e descrição.

## Task 10: Editor — pipeline e análise
Nível: 5
Status: -1

- Subtask 10.1: Recebimento: pega da fila de pesca, identifica operação, item e preset.
- Subtask 10.2: Análise com ffprobe: resolução, proporção, FPS, duração, codecs, áudio, integridade.
- Subtask 10.3: Snapshot do preset (versão e perfil de rede) congelado na execução.
- Subtask 10.4: Orquestração das etapas, com status por etapa e registro em `events`.
- Subtask 10.5: Falha em um vídeo não interrompe os demais. Sucesso solta na fila de editados.

## Task 11: Padronização e enquadramento
Nível: 5
Status: -1

- Subtask 11.1: Conversão para resolução, FPS, pixel format e codecs do preset.
- Subtask 11.2: Modo A (preencher), com posição do corte configurável.
- Subtask 11.3: Modo B (ajustar), com cor de fundo.
- Subtask 11.4: Modo C (fundo desfocado), com intensidade configurável.
- Subtask 11.5: Testes com horizontal, vertical e quadrado.

## Task 12: Máscaras PNG
Nível: 4
Status: -1

- Subtask 12.1: Importação e armazenamento em `mask_assets` e `mask_versions`, com checksum.
- Subtask 12.2: Validação: integridade, PNG, dimensões, canal alfa, compatibilidade e proporção.
- Subtask 12.3: Posicionamento, escala, opacidade e alinhamento.
- Subtask 12.4: Sobreposição em camada superior ao vídeo.
- Subtask 12.5: Cada render guarda `mask_version_id`.

## Task 13: Textos e elementos gráficos
Nível: 4
Status: -1

- Subtask 13.1: Texto desenhado em PNG pelo Pillow e sobreposto pelo FFmpeg.
- Subtask 13.2: Somente textos fixos do preset: o título não vai escrito no vídeo (decidido).
- Subtask 13.3: Posições predefinidas e personalizada, com margens de segurança.
- Subtask 13.4: Logotipo, marca d'água própria e imagens adicionais (PNG) com posição, escala e opacidade.

## Task 14: Áudio
Nível: 4
Status: -1

- Subtask 14.1: Preservar, remover ou substituir.
- Subtask 14.2: Volume, normalização de loudness, fade-in e fade-out.
- Subtask 14.3: Saída AAC quando há faixa de áudio.
- Subtask 14.4: Permissão de uso do áudio substituto registrada no preset.

## Task 15: Presets e versionamento
Nível: 5
Status: -1

- Subtask 15.1: Preset dentro do JSON versionado da operação.
- Subtask 15.2: Formulário de configuração em seções, sem timeline e sem prévia editável.
- Subtask 15.3: Ações: salvar, duplicar, ativar, consultar histórico.
- Subtask 15.4: "Testar preset": render de amostra com relatório de QC, que mede também tempo e tamanho reais.
- Subtask 15.5: Execução iniciada guarda snapshot.

## Task 16: Títulos e metadados (Postador)
Nível: 3
Status: -1

- Subtask 16.1: Gerados pelo Postador na hora da publicação (decidido).
- Subtask 16.2: Cadeia de Markov de ordem 2 no corpus, com filtros de tamanho, palavras bloqueadas, cópia e repetição.
- Subtask 16.3: Fallback para templates; registrar `title_method`.
- Subtask 16.4: Descrição a partir de template e hashtags por plataforma.

## Task 17: Controle de qualidade (QC)
Nível: 5
Status: -1

- Subtask 17.1: Verificações técnicas do render (abre, resolução, proporção, FPS, codec, duração, áudio, máscara, armazenado).
- Subtask 17.2: Impeditivo bloqueia; aviso passa e fica visível.
- Subtask 17.3: Falha impeditiva: registrar, marcar falha, preservar original, permitir reprocessamento.
- Subtask 17.4: Retry automático só para erro de processo (proposta: 2 tentativas).

## Task 18: Aprovação
Nível: 5
Status: -1

- Subtask 18.1: Tela de aprovação com player do R2 por URL assinada, origem, permissão, QC e contas.
- Subtask 18.2: Aprovar, rejeitar, nova versão (novo render com o preset atual).
- Subtask 18.3: Aprovação vale para um render exato e para as contas autorizadas.
- Subtask 18.4: Aprovação em lote em grade, bloqueando QC impeditivo ou sem permissão.
- Subtask 18.5: Botão "Aprovar automaticamente" por operação: aprova quem passa no QC, tem permissão e não é duplicado (decidido).

---

## Task 19: Contas
Nível: 5
Status: -1

- Subtask 19.1: Tabela `accounts` e vínculo com operações (REQ-ACC-001).
- Subtask 19.2: Conexão por OAuth oficial, com retorno na interface (Vercel).
- Subtask 19.3: Token criptografado no banco; chave nas variáveis de ambiente da Vercel e da VPS.
- Subtask 19.4: `daily_limit` por conta (proposta: 3 por dia até medir).
- Subtask 19.5: Tela de contas: conectar, testar, pausar, revogar.
- Subtask 19.6: Token inválido → conta em erro e envios dela pendentes; outras contas não são afetadas.

## Task 20: Adaptador YouTube Shorts
Nível: 5
Status: -1

- Subtask 20.1: Interface `PlatformAdapter` (`publish`, `check`, `capabilities`).
- Subtask 20.2: Upload com controle da cota (100 por dia por projeto, somando todas as operações).
- Subtask 20.3: Pedir a auditoria do projeto ao Google (sem ela, os vídeos saem privados).

## Task 21: Distribuição
Nível: 5
Status: -1

- Subtask 21.1: Tela Nova publicação (manual): vídeos aprovados, contas, intervalo, primeira imediata, início, prévia da agenda.
- Subtask 21.2: Distribuição automática quando ligada na operação.
- Subtask 21.3: Modo rodízio (padrão): cada vídeo vai para um canal só, alternando os canais ao longo da janela.
- Subtask 21.4: Modo "todos os canais": o mesmo vídeo em cada conta.
- Subtask 21.5: Canal com erro ou no limite é pulado e o próximo assume.

## Task 22: Cálculo de horários
Nível: 5
Status: -1

- Subtask 22.1: T0 e horário n = T0 + (n − 1) × intervalo, por conta.
- Subtask 22.2: No rodízio, espaçamento = janela ÷ vídeos do dia.
- Subtask 22.3: Janela de publicação e limite diário (REQ-DIST-014).
- Subtask 22.4: Além de 7 dias → `pending_capacity` com motivo, reavaliado diariamente.
- Subtask 22.5: Fuso horário por conta (padrão `America/Sao_Paulo`).

## Task 23: Criação de envios e idempotência
Nível: 5
Status: -1

- Subtask 23.1: `request_key` única por lote (REQ-DIST-011).
- Subtask 23.2: Um `publish_job` por par vídeo × conta, após validar aprovação e conta.
- Subtask 23.3: Mesmo `sha256` já publicado na conta → `skipped` com motivo.
- Subtask 23.4: Restrição única `(render_id, account_id)`.

## Task 24: Estados do envio, falhas, retries e exclusão
Nível: 5
Status: -1

- Subtask 24.1: Máquina de estados do envio (seção 9.4 da v2.1).
- Subtask 24.2: Rate limit: `retry_wait` de 2, 10 e 30 minutos; depois `failed`.
- Subtask 24.3: Timeout → `uncertain` e `adapter.check()` antes de qualquer retry; sem check, decisão manual.
- Subtask 24.4: Retry só no envio que falhou (REQ-DIST-010).
- Subtask 24.5: Publicado → fila de exclusão. A Limpeza apaga original e render X minutos após a última publicação do vídeo (padrão 30); envios incertos ou com falha não são apagados.
- Subtask 24.6: Itens rejeitados e duplicados também são apagados X minutos após a decisão. Registros, hashes e links ficam.

---

## Task 25: Dashboard e navegação
Nível: 3
Status: -1

- Subtask 25.1: Menu com 6 itens: Dashboard, Operações, Fila, Aprovação, Publicações, Contas.
- Subtask 25.2: Cards clicáveis que abrem a fila filtrada (REQ-UI-001), incluindo estoque de editados.
- Subtask 25.3: Painel de erros alimentado por `events`.

## Task 26: Testes e critérios de aceitação
Nível: 5
Status: -1

- Subtask 26.1: Critérios da v2.1 (12).
- Subtask 26.2: Critérios do editor Nível 1 (20), em `docs/editor-nivel-1.md`.
- Subtask 26.3: Teste de arquitetura: o core não importa `networks/`.
- Subtask 26.4: Teste de reprodutibilidade do render.

## Task 27: Deploy e operação
Nível: 3
Status: 0

- Subtask 27.1: Interface na Vercel (`app.py` + `vercel.json`) e variáveis de ambiente. Feito: projeto `fea` (time OHalla) com preview da branch no ar; produção sai quando a branch entrar no `main`.
- Subtask 27.2: Banco Neon pelo Marketplace da Vercel; migrações aplicadas pelo CI ou manualmente.
- Subtask 27.3: Workers na VPS com Docker Compose (Buscador, Editor, Postador, Limpeza).
- Subtask 27.4: Bucket no Cloudflare R2 com URLs assinadas.
- Subtask 27.5: Backup do banco e healthcheck da interface e dos workers.

## Task 28: Fase 4 — Expansão
Nível: 2
Status: -1

- Subtask 28.1: Buscadores de X e TikTok (verificar API, regras e custo de cada um).
- Subtask 28.2: Perfis e adaptadores TikTok e Instagram Reels.
- Subtask 28.3: Métricas de engajamento.

## Task 29: Decisões
Nível: 4
Status: 0

- Subtask 29.1: Fila de tarefas: **Postgres** (decidido).
- Subtask 29.2: Tabelas: **14** (decidido).
- Subtask 29.3: Armazenamento: **Cloudflare R2** (decidido).
- Subtask 29.4: Editor: **sem área de edição**, tudo por preset (decidido).
- Subtask 29.5: Retenção: **X minutos após a última publicação, padrão 30** (decidido).
- Subtask 29.6: Biblioteca do canvas: **Drawflow** (decidido).
- Subtask 29.7: Canvas só configura o fluxo (decidido).
- Subtask 29.8: Aprovação automática: **botão por operação** (decidido).
- Subtask 29.9: Título só na publicação, gerado pelo Postador (decidido).
- Subtask 29.10: Pendente: comunidades do Reddit autorizadas.
- Subtask 29.11: Pendente: acordo comercial com o Reddit, se o canal for monetizado.
- Subtask 29.12: Pendente: plano da Vercel (Hobby é só para uso não comercial).
- Subtask 29.13: Pendente: se o Google aceita `.vercel.app` no OAuth em produção.
- Subtask 29.14: Pendente: limites gratuitos do Neon.
- Subtask 29.15: Pendente: tentativas automáticas do render (proposta: 2) e permissão do áudio substituto.

---

## Fora desta versão

Vários usuários com papéis, fair scheduling entre operações, alertas proativos, custo por vídeo, timeline e editor manual, thumbnail personalizada, rastreamento de rostos e objetos, legendas automáticas, cortes inteligentes, construtor de máscaras, remoção de marca d'água de terceiros.
