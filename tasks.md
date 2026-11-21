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
| Interface | Vercel (FastAPI + Jinja2 + HTMX) | Telas, fluxo, aprovação, Acessos, retorno do OAuth |
| Banco | Neon (Postgres, via Vercel Marketplace) | Dados, versões e fila de tarefas |
| Processamento | VPS com Docker: um ambiente isolado por operação + núcleo, administrados por um agente (Tasks 30 a 35) | Buscador, Editor, Postador e Limpeza |
| Arquivos | Cloudflare R2 | Originais, renders e máscaras |

Fluxo: Buscador → fila de pesca → Editor → fila de editados → (aprovação manual ou automática) → Postador → fila de exclusão → Limpeza (X minutos após a publicação, padrão 30).

## Mapa de fases

Blocos do produto (ver `docs/fluxo-operacao.md`): **Pesca** (Tasks 5 a 8), **Motor Editor** (Tasks 9 a 18), **Publicador** (Tasks 19 a 24). Ligados no fluxo da operação (Task 4).

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
- Subtask 4.8: **Editor de operação** num lugar só: barra superior (nome editável, versão, estado, desfazer/refazer, Salvar, Executar), abas Fluxo/Configurações/Logs, malha pontilhada com nós compactos (Busca → Edição → destinos de Publicação em ramificação), ferramentas (selecionar, biblioteca de módulos, lista de módulos, histórico de versões, enquadrar), zoom, minimapa, arrastar nós, inspector contextual à direita e barra de validação com "Ativar operação". Só configura o fluxo; não edita vídeo (decidido).
- Subtask 4.9: Ligações fora da tabela de tipos de porta são recusadas com motivo.
- Subtask 4.10: Clicar no nó abre o inspector: Busca (fontes Reddit/X/upload com teste de conexão, filtros e tags, quantidade, automação), Edição (formato, máscara PNG com importação, marca d'água própria, áudio, enquadramento, avançado) e cada destino de Publicação (contas da rede, privacidade, aprovação, agendamento, título e descrição, limpeza). Versões podem ser restauradas (vira uma versão nova).
- Subtask 4.11: Validação antes de ativar: Fonte → Pesca → Edição → Aprovação → Postagem; uma Rede ligada a Edição e Postagem; ao menos uma Conta; sem ciclos.
- Subtask 4.12: Grafo (nós, arestas e configs) salvo como JSON versionado em `operation_configs`. Cada execução guarda snapshot.
- Subtask 4.13: Operação arquivada abre o canvas em somente leitura, com opção de duplicar.

## Task 5: Fontes e conectores (Buscador)
Nível: 4
Status: 1

- Subtask 5.1: Cadastro de fonte por operação (`type`, `reference`, `permission_note`, `status`, `cursor`, `last_error`).
- Subtask 5.2: `permission_note` obrigatório. Sem ele, os itens entram como `pending_permission` (REQ-UI-004).
- Subtask 5.3: Interface `SourceConnector` (`fetch`, `search(tags, cursor)`, `download`) e modelo `RawItem`.
- Subtask 5.4: Conector de upload manual (envio direto do navegador ao R2 por URL assinada).
- Subtask 5.5: Conector Reddit pela API oficial, só em comunidades com autorização registrada. Vídeo e áudio vêm separados e o FFmpeg junta.
- Subtask 5.6: Erro temporário: até 3 tentativas com espera crescente.
- Subtask 5.7: Credencial inválida ou fonte removida: `status=error`, aparece no dashboard, e a execução segue com as outras fontes.
- Subtask 5.8: Vários Buscadores por operação: cada bloco Fonte é um Buscador próprio, todos soltando na mesma fila de pesca. Pronto para novos conectores em `core/connectors` (MVP: Reddit e upload).

## Task 6: Execução (Play), modo automático e estoque
Nível: 5
Status: 1

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
Status: 1

- Subtask 7.1: Máquina de estados do item (tabela da seção 6.1 da v2.1).
- Subtask 7.2: Checagem de formato, duração (`max_duration_s`), palavra bloqueada e nicho → `rejected`.
- Subtask 7.3: Deduplicação em ordem:
  - Subtask 7.3.1: Mesmo item externo `(source_id, external_id)`, escopo da fonte.
  - Subtask 7.3.2: Mesmo arquivo por `sha256`, escopo global.
  - Subtask 7.3.3: Imagem parecida por `phash` com distância ≤ 6, escopo global, sobre 3 quadros (10%, 50%, 90%).
- Subtask 7.4: Duplicado de outra operação recebe `duplicate` com `duplicate_of`.
- Subtask 7.5: Classificação: score = tags (1) + heat tags (2). Score 0 com tags configuradas → `rejected`.
- Subtask 7.6: Permissão: o item herda o `permission_note` da fonte. Sem permissão → `pending_permission`, sem baixar nada. Liberar ou rejeitar em lote fica na fila (Task 8).
- Subtask 7.7: Detecção de marca d'água de terceiro por OCR (Tesseract) em 3 quadros: nome de outra rede ou @ que persiste → `rejected` com motivo. Nunca remove a marca. Configurável por `reject_watermarks` no bloco Pesca.

## Task 8: Filas
Nível: 4
Status: 1

- Subtask 8.1: Fila geral com colunas: item, operação, execução, etapa/estado, prioridade, score, data, erro, ação.
- Subtask 8.2: Fila da operação é a mesma tela com filtro `operation_id` (REQ-QUEUE-003).
- Subtask 8.3: Filtros por operação e por etapa (pesca, editados, exclusão e estados da REQ-QUEUE-005).
- Subtask 8.4: Seleção em lote com resumo antes de confirmar (REQ-UI-005).
- Subtask 8.5: Ordenação por prioridade da execução, depois por score.

---

## Task 9: Módulo de redes sociais (perfis)
Nível: 5
Status: 1

- Subtask 9.1: Interface `NetworkProfile`: saída padrão, restrições, regras de QC, limites de metadados, capacidades, adaptador.
- Subtask 9.2: Registro de perfis carregado pelo core. Cada operação escolhe um perfil.
- Subtask 9.3: Validação do preset contra o perfil ao salvar.
- Subtask 9.4: O core não importa código de rede (teste de arquitetura).
- Subtask 9.5: Perfil `youtube_shorts`: 9:16, 1080 × 1920, MP4, H.264, AAC, 30 FPS, yuv420p, até 3 minutos.
- Subtask 9.6: Confirmar no console do Google Cloud a cota e os limites de título e descrição.

## Task 10: Editor — pipeline e análise
Nível: 5
Status: 1

- Subtask 10.1: Recebimento: pega da fila de pesca, identifica operação, item e preset.
- Subtask 10.2: Análise com ffprobe: resolução, proporção, FPS, duração, codecs, áudio, integridade.
- Subtask 10.3: Snapshot do preset (versão e perfil de rede) congelado na execução.
- Subtask 10.4: Orquestração das etapas, com status por etapa e registro em `events`.
- Subtask 10.5: Falha em um vídeo não interrompe os demais. Sucesso solta na fila de editados.

## Task 11: Padronização e enquadramento
Nível: 5
Status: 1

- Subtask 11.1: Conversão para resolução, FPS, pixel format e codecs do preset.
- Subtask 11.2: Modo A (preencher), com posição do corte configurável.
- Subtask 11.3: Modo B (ajustar), com cor de fundo.
- Subtask 11.4: Modo C (fundo desfocado), com intensidade configurável.
- Subtask 11.5: Testes com horizontal, vertical e quadrado.

## Task 12: Máscaras PNG
Nível: 4
Status: 1

- Subtask 12.1: Importação e armazenamento em `mask_assets` e `mask_versions`, com checksum.
- Subtask 12.2: Validação: integridade, PNG, dimensões, canal alfa, compatibilidade e proporção.
- Subtask 12.3: Posicionamento, escala, opacidade e alinhamento.
- Subtask 12.4: Sobreposição em camada superior ao vídeo.
- Subtask 12.5: Cada render guarda `mask_version_id`.

## Task 13: Textos e elementos gráficos
Nível: 4
Status: 1

- Subtask 13.1: Texto desenhado em PNG pelo Pillow e sobreposto pelo FFmpeg.
- Subtask 13.2: Somente textos fixos do preset: o título não vai escrito no vídeo (decidido).
- Subtask 13.3: Posições predefinidas e personalizada, com margens de segurança.
- Subtask 13.4: Logotipo, marca d'água própria e imagens adicionais (PNG) com posição, escala e opacidade.

## Task 14: Áudio
Nível: 4
Status: 1

- Subtask 14.1: Preservar, remover ou substituir.
- Subtask 14.2: Volume, normalização de loudness, fade-in e fade-out.
- Subtask 14.3: Saída AAC quando há faixa de áudio.
- Subtask 14.4: Permissão de uso do áudio substituto registrada no preset.

## Task 15: Presets e versionamento
Nível: 5
Status: 1

- Subtask 15.1: Preset dentro do JSON versionado da operação.
- Subtask 15.2: Formulário de configuração em seções, sem timeline e sem prévia editável.
- Subtask 15.3: Ações: salvar, duplicar, ativar, consultar histórico.
- Subtask 15.4: "Testar preset": render de amostra com relatório de QC, que mede também tempo e tamanho reais.
- Subtask 15.5: Execução iniciada guarda snapshot.

## Task 16: Títulos e metadados (Postador)
Nível: 3
Status: 1

- Subtask 16.1: Gerados pelo Postador na hora da publicação (decidido).
- Subtask 16.2: Cadeia de Markov de ordem 2 no corpus, com filtros de tamanho, palavras bloqueadas, cópia e repetição.
- Subtask 16.3: Fallback para templates; registrar `title_method`.
- Subtask 16.4: Descrição a partir de template e hashtags por plataforma.

## Task 17: Controle de qualidade (QC)
Nível: 5
Status: 1

- Subtask 17.1: Verificações técnicas do render (abre, resolução, proporção, FPS, codec, duração, áudio, máscara, armazenado).
- Subtask 17.2: Impeditivo bloqueia; aviso passa e fica visível.
- Subtask 17.3: Falha impeditiva: registrar, marcar falha, preservar original, permitir reprocessamento.
- Subtask 17.4: Retry automático só para erro de processo (proposta: 2 tentativas).

## Task 18: Aprovação
Nível: 5
Status: 1

- Subtask 18.1: Tela de aprovação com player do R2 por URL assinada, origem, permissão, QC e contas.
- Subtask 18.2: Aprovar, rejeitar, nova versão (novo render com o preset atual).
- Subtask 18.3: Aprovação vale para um render exato e para as contas autorizadas.
- Subtask 18.4: Aprovação em lote em grade, bloqueando QC impeditivo ou sem permissão.
- Subtask 18.5: Botão "Aprovar automaticamente" por operação: aprova quem passa no QC, tem permissão e não é duplicado (decidido).

---

## Task 19: Contas
Nível: 5
Status: 1

- Subtask 19.1: Tabela `accounts` e vínculo com operações (REQ-ACC-001).
- Subtask 19.2: Conexão por OAuth oficial, com retorno na interface (Vercel).
- Subtask 19.3: Token criptografado no banco; chave nas variáveis de ambiente da Vercel e da VPS.
- Subtask 19.4: `daily_limit` por conta (proposta: 3 por dia até medir).
- Subtask 19.5: Tela de contas: conectar, testar, pausar, revogar.
- Subtask 19.6: Token inválido → conta em erro e envios dela pendentes; outras contas não são afetadas.

## Task 20: Adaptador YouTube Shorts
Nível: 5
Status: 1

- Subtask 20.1: Interface `PlatformAdapter` (`publish`, `check`, `capabilities`).
- Subtask 20.2: Upload com controle da cota (100 por dia por projeto, somando todas as operações).
- Subtask 20.3: Pedir a auditoria do projeto ao Google (sem ela, os vídeos saem privados). **Ação do usuário** (docs/configuracao.md, seção 7).

## Task 21: Distribuição
Nível: 5
Status: 1

- Subtask 21.1: Tela Nova publicação (manual): vídeos aprovados, contas, intervalo, primeira imediata, início, prévia da agenda.
- Subtask 21.2: Distribuição automática quando ligada na operação.
- Subtask 21.3: Modo rodízio (padrão): cada vídeo vai para um canal só, alternando os canais ao longo da janela.
- Subtask 21.4: Modo "todos os canais": o mesmo vídeo em cada conta.
- Subtask 21.5: Canal com erro ou no limite é pulado e o próximo assume.

## Task 22: Cálculo de horários
Nível: 5
Status: 1

- Subtask 22.1: T0 e horário n = T0 + (n − 1) × intervalo, por conta.
- Subtask 22.2: No rodízio, espaçamento = janela ÷ vídeos do dia.
- Subtask 22.3: Janela de publicação e limite diário (REQ-DIST-014).
- Subtask 22.4: Além de 7 dias → `pending_capacity` com motivo, reavaliado diariamente.
- Subtask 22.5: Fuso horário por conta (padrão `America/Sao_Paulo`).

## Task 23: Criação de envios e idempotência
Nível: 5
Status: 1

- Subtask 23.1: `request_key` única por lote (REQ-DIST-011).
- Subtask 23.2: Um `publish_job` por par vídeo × conta, após validar aprovação e conta.
- Subtask 23.3: Mesmo `sha256` já publicado na conta → `skipped` com motivo.
- Subtask 23.4: Restrição única `(render_id, account_id)`.

## Task 24: Estados do envio, falhas, retries e exclusão
Nível: 5
Status: 1

- Subtask 24.1: Máquina de estados do envio (seção 9.4 da v2.1).
- Subtask 24.2: Rate limit: `retry_wait` de 2, 10 e 30 minutos; depois `failed`.
- Subtask 24.3: Timeout → `uncertain` e `adapter.check()` antes de qualquer retry; sem check, decisão manual.
- Subtask 24.4: Retry só no envio que falhou (REQ-DIST-010).
- Subtask 24.5: Publicado → fila de exclusão. A Limpeza apaga original e render X minutos após a última publicação do vídeo (padrão 30); envios incertos ou com falha não são apagados.
- Subtask 24.6: Itens rejeitados e duplicados também são apagados X minutos após a decisão. Registros, hashes e links ficam.

---

## Task 25: Dashboard e navegação
Nível: 3
Status: 1

- Subtask 25.1: Menu com 6 itens: Dashboard, Operações, Fila, Aprovação, Publicações, Contas.
- Subtask 25.2: Cards clicáveis que abrem a fila filtrada (REQ-UI-001), incluindo estoque de editados.
- Subtask 25.3: Painel de erros alimentado por `events`.

## Task 26: Testes e critérios de aceitação
Nível: 5
Status: 1

- Subtask 26.1: Critérios da v2.1 (12).
- Subtask 26.2: Critérios do editor Nível 1 (20), em `docs/editor-nivel-1.md`.
- Subtask 26.3: Teste de arquitetura: o core não importa `networks/`.
- Subtask 26.4: Teste de reprodutibilidade do render.

## Task 27: Deploy e operação
Nível: 3
Status: 0

- Subtask 27.1: Interface na Vercel (`app.py` + `vercel.json`) e variáveis de ambiente. Feito: branch mesclada no `main` (PR #1), produção em `https://fea-rho.vercel.app`; `PUBLIC_BASE_URL`, `SECRET_KEY`, `TOKEN_ENCRYPTION_KEY`, `GITHUB_ALLOWED_ID` e `APP_ENV` definidos. **Falta: `GITHUB_CLIENT_ID`/`GITHUB_CLIENT_SECRET` (usuário).**
- Subtask 27.2: Banco Neon pelo Marketplace da Vercel; migrações aplicadas pelo CI ou manualmente. Pronto no código: botão "Aplicar migrações" na tela Acessos e serviço `migrar` da VPS. **Falta: criar o Neon (um clique do usuário na Vercel).**
- Subtask 27.3: Workers na VPS com Docker Compose (Buscador, Editor, Postador, Limpeza). Pronto: `deploy/docker-compose.vps.yml` e o comando de instalação gerado na tela Acessos (uso único, 30 min, já traz banco e chave); sinal de vida dos workers na tela Acessos. **Falta: criar a VPS na Oracle (usuário).**
- Subtask 27.4: Bucket no Cloudflare R2 com URLs assinadas. Pronto no código (`R2Storage`); as chaves entram pela tela Acessos e valem para interface e workers. **Falta: criar o bucket e o token (usuário).**
- Subtask 27.5: Backup do banco e healthcheck da interface e dos workers. Feito: `/health` na interface, `python -m worker alive` (heartbeat) no healthcheck do Docker, serviço `backup` diário com 14 dias.

## Task 28: Fase 4 — Expansão
Nível: 2
Status: 1

- Subtask 28.1: Buscador do X pela API v2 oficial (busca recente, Bearer Token; exige plano pago). Buscador do TikTok **não entra**: a única API de busca do TikTok é a Research API, restrita a pesquisadores; coleta sem API oficial fica fora (decidido).
- Subtask 28.2: Perfis e adaptadores TikTok (Content Posting API, Direct Post) e Instagram Reels (Instagram API with Instagram Login), com OAuth, renovação de token e envio assíncrono (`processing` → consulta → `published`). Uma operação pode publicar em várias redes; o vídeo segue o padrão comum a todas.
- Subtask 28.3: Métricas por envio (views, curtidas, comentários) atualizadas a cada 6 h por 30 dias, na tela Publicações.
- Subtask 28.4: Tela **Acessos**: estado das variáveis da ferramenta, chaves de Reddit, X, Google, TikTok e Instagram preenchidas pela interface (criptografadas no banco, valem para interface e workers), endereços de retorno e login OAuth de cada conta.
- Subtask 28.5: Visual revisto: mais limpo, cantos levemente arredondados, sóbrio e minimalista.
- Subtask 28.6: Limite de uso do R2: a ferramenta conta gravações (Classe A), leituras (Classe B) e o pico de armazenamento do mês, mede o bucket de hora em hora (Limpeza) e para ao chegar no percentual escolhido da franquia grátis (padrão 80%). Painel e ajuste no Dashboard.
- Subtask 28.7: Páginas públicas com as exigências da auditoria da API do YouTube (aviso de uso dos YouTube API Services, links dos Termos do YouTube e da política do Google, revogação, exclusão e uso limitado) e guia `docs/auditoria-youtube.md` com as respostas do formulário, os arquivos pedidos e o roteiro do screencast.
- Subtask 28.8: Fonte **Google Drive**: pasta lida por conta de serviço (pasta privada) ou por chave de API (pasta com link público, para quem tem a criação de chaves bloqueada por política da organização). Sem escopo restrito no OAuth e sem verificação; teste da chave em Acessos e download por streaming.
- Subtask 28.9: Workers no próprio computador (Docker Desktop): botão "Baixar .env" em Acessos e guia `docs/workers-no-computador.md`.
- Subtask 28.10: `docs/rumos.md`: alternativas pesquisadas para fontes, hospedagem dos workers e redes de publicação, com o plano da versão de início.
- Subtask 28.11: Workers no celular Android (Termux): instalador `web/static/instalar-termux.sh` e guia `docs/workers-no-celular.md`. Não testado em aparelho real.
- Subtask 28.12: Versão do código nos workers: cada worker informa o commit que roda; a tela Acessos avisa quando difere do site e manda rodar `fea-atualizar` (Termux) ou o instalador (VPS). A tela Executar mostra o motivo do erro de cada fonte e testa a conexão ali mesmo.
- Subtask 28.13: Painel dos workers no terminal (`fea-painel`, também na VPS): tela que se redesenha no lugar, verbo de cada worker no gerúndio, barra e porcentagem reais (FFmpeg e busca), bolinha verde ou vermelha, `/log` com os detalhes. A chave de API do Google em URLs não vai mais para os logs.
- Subtask 28.14: Dashboard com 3 indicadores em gráfico (publicações por dia, funil de vídeos, saúde dos workers) e o resto numa lista compacta. Operações com estado ao vivo (rodinha, estágios Buscando/Editando/Publicando com ícones, barra em andamento, vermelho em caso de erro), atualizado a cada 5 s sem recarregar. Lista de operações em cartões no celular.

## Task 30: Plataforma — análise e decisões
Nível: 4
Status: 1

- Subtask 30.1: Análise do "Manual de Implantação: Operations Infrastructure Platform v1.0" e adaptação viável em `docs/plataforma.md`: mantém o painel FastAPI (Control Plane), o Neon e a fila no Postgres; troca Docker Controller exposto por um agente *pull* na VPS; Redis/BullMQ, Grafana e RLS ficam para fases seguintes, com o motivo de cada um.
- Subtask 30.2: Isolamento para segurança, organização e continuidade, não anonimato: sem IP por operação, sem proxies.

## Task 31: Escopo por operação na fila e nos workers
Nível: 4
Status: 1

- Subtask 31.1: Toda tarefa de publicação carrega o `operation_id` (envio → render → item), como as de busca e edição.
- Subtask 31.2: Worker com `OPERATION_ID` só pega tarefas da sua operação; worker do núcleo (`FEA_SCOPE=nucleo`) só pega as sem operação (agenda, limpeza, renovação); sem nada definido, pega tudo (celular e instalação antiga continuam funcionando).
- Subtask 31.3: Uma falha numa operação nunca cancela tarefas de outra (filas separadas por escopo).

## Task 32: Estado desejado e estado real
Nível: 4
Status: 1

- Subtask 32.1: Tabelas `operation_runtimes` (estado desejado, limites de CPU e memória, versão, estado real, containers, uso de recursos, erro, logs recentes, pedidos de reinício e backup) e `infra_servers` (servidor, versão do agente, CPU, memória, disco, carga, último sinal, versões disponíveis).
- Subtask 32.2: Regras em `core/platform.py`: iniciar, parar, reiniciar, limites válidos, versão, pedido de backup e restauração, auditoria em `events`.

## Task 33: Agente da VPS (Operations Manager, Docker Controller, Resource Manager, Health Monitor, Version Manager)
Nível: 5
Status: 1

- Subtask 33.1: Gera `/opt/fea/operations/op-<id>/compose.yml` a partir do modelo: serviços busca, edição e publicação, `OPERATION_ID`, limites, rede própria, sem portas, `no-new-privileges`, sem capabilities, raiz só de leitura, volumes exclusivos, healthcheck e logs com rotação.
- Subtask 33.2: Reconciliação a cada 15 s: sobe, para e recria cada operação conforme o estado desejado; o núcleo sempre no ar; idempotente.
- Subtask 33.3: Coleta e reporta estado dos containers, CPU, memória e disco (servidor e operação), logs recentes sem segredos e falhas.
- Subtask 33.4: Versões: imagem `fea-worker:<commit>`; cada operação fixa uma versão ou acompanha a mais nova; rollback para uma versão anterior disponível.
- Subtask 33.5: Socket do Docker só local; nenhuma porta aberta para a internet.
- Subtask 33.6: Verificado com Docker real (núcleo + duas operações): cada tarefa executada pelo ambiente da própria operação; operação 1 não alcança a 2 pela rede; raiz só de leitura, sem capabilities, sem portas, com limites; parar uma não afeta a outra; backup e restauração; versão inexistente vira erro sem derrubar; nenhum segredo nos logs; worker solto (celular) para sozinho em segundos.

## Task 34: Painel da plataforma
Nível: 4
Status: 1

- Subtask 34.1: Aba "Ambiente" na operação: estado real e desejado, iniciar, parar, reiniciar, limites, versão (atualizar e voltar), logs recentes, CPU e memória, backup e restauração.
- Subtask 34.2: Servidor em Acessos → Workers: CPU, memória, disco, versão do agente e operações hospedadas.
- Subtask 34.3: Estado ao vivo da operação inclui o ambiente (parado, subindo, no ar, com falha).
- Subtask 34.4: Verificado com o agente real: clicar em Parar no painel parou só os containers daquela operação em menos de 20 s, e a tela passou a mostrar "Parado".

## Task 35: Instalador e migração em um comando
Nível: 5
Status: 1

- Subtask 35.1: Instalador idempotente: verifica distribuição, arquitetura e recursos; instala Docker e Compose; firewall (só SSH); `/opt/fea` com permissões; segredos em arquivo 0600; constrói a imagem; sobe núcleo e agente; verifica a saúde.
- Subtask 35.2: Migração do celular: o agente marca a plataforma como ativa e cria o ambiente de cada operação ativa; os workers do celular param sozinhos ("migrado para a VPS").
- Subtask 35.3: Backup e restauração dos arquivos de cada operação pelo painel; dump diário do banco no núcleo. Pendente: cópia fora da VPS (R2) depois de medir o tamanho.
- Subtask 35.4: Verificação real do instalador numa máquina Ubuntu com Docker (`FEA_HOME`, `FEA_REPO` e `FEA_IMAGE` permitem testar sem GitHub nem build): duas execuções seguidas, agente e núcleo no ar, ambientes das operações recriados, segredos intactos (0600). Bug achado e corrigido: sem `sshd` o `pipefail` abortava o instalador. Firewall e instalação do Docker por apt não puderam ser testados aqui (rede restrita).

## Task 38: Fluxo sem autorizações manuais
Nível: 2
Status: 1

- Subtask 38.1: Trava de permissão da fonte removida: os itens não param mais em "sem permissão" e o campo saiu do editor, da aba Fontes, da revisão e do dashboard. Itens antigos parados nesse estado saem com "Liberar" na fila.
- Subtask 38.2: Opção "Autorizar tudo" no bloco Aprovação: o que passa no controle de qualidade é aprovado para as contas da operação e a distribuição automática liga junto, sem depender de aprovação manual.
- Responsabilidade: a origem do conteúdo e os direitos de uso continuam sendo do operador; as políticas das plataformas (direitos autorais, conteúdo reutilizado) valem igual.

## Task 39: Short com várias imagens e música aleatória
Nível: 3
Status: 1

- Subtask 39.1: "Agrupar imagens" no bloco Edição: junta N imagens (2 a 20) num só vídeo, uma após a outra, com o enquadramento e a camada fixa (máscara, marca d'água, textos) do preset. A duração por imagem é a do preset e encolhe sozinha se o total passar do limite da rede. Ligar a opção já inclui imagens na busca.
- Subtask 39.2: Imagens que sobram (menos que N) esperam as próximas da pesca, sem falhar. Se o render do grupo falhar, as imagens extras voltam à pesca (estado novo `grouped`, migração 0011).
- Subtask 39.3: Áudio "Música aleatória": sorteia uma música da biblioteca da operação a cada vídeo. Sem a opção (áudio "Nenhum"), o vídeo sai sem música e segue para a publicação normal.
- Subtask 39.4: Imagem corrompida é recusada antes do FFmpeg (ele entraria em laço sem fim).
- Limite conhecido: o YouTube não oferece API de "músicas em alta" para Shorts, e música comercial gera reivindicação de direitos autorais. A biblioteca é de músicas que o operador envia (próprias, licenciadas ou da Biblioteca de Áudio do YouTube). Pendente, se desejado: sugerir músicas da Biblioteca de Áudio do YouTube.

## Task 40: Busca no Drive sem travas (memes)
Nível: 2
Status: 1

- Subtask 40.1: Worker reiniciado (ex.: `fea-atualizar`) devolve na hora as tarefas que deixou presas; antes ficavam 30 minutos em "rodando" e a busca parecia parada em "1 examinado".
- Subtask 40.2: Repetidos não barram mais por padrão; opção "Bloquear repetidos" no bloco Busca para ligar depois.
- Subtask 40.3: Fontes sem busca por texto (Drive, upload): sem tags, ordem aleatória; com tags, os que casam com elas vêm primeiro e o resto não é descartado. Arquivos já vistos na fonte continuam pulados (não repete).
- Subtask 40.4: Com "Agrupar imagens", a meta X conta vídeos: busca X × N imagens e manda todas para a edição (antes só X entravam e saía 1 Short).
- Subtask 40.5: Itens presos de rodadas antigas ("sem permissão", "duplicado" com repetidos liberados, "fora do nicho" no Drive) voltam a ser processados em vez de contar como "já vistos" para sempre (a busca rodava, pulava tudo e parava). Quando a pasta só tem arquivos já usados, a execução diz isso.

## Task 41: Tela de Diagnóstico
Nível: 1
Status: 1

- Subtask 41.1: `/diagnostico` (menu): migração do banco, workers (no ar, versão), tarefas das últimas 6 h com erros e presas, e por operação a configuração efetiva, fontes, últimas execuções (contadores e motivo de parada) e o destino de cada item. Texto único com botão de copiar, sem segredos.

## Task 42: Workers do celular que não morrem de vez
Nível: 2
Status: 1

- Subtask 42.1: `deploy/termux/ligar.sh`: cada worker roda num laço e religa em 10 s se o Android o derrubar (antes ficava morto e a operação parava no meio). Testado com `kill -9`: religou sozinho; `desligar.sh` não deixa processo para trás.
- Subtask 42.2: `fea-ligar` e `fea-desligar` chamam os scripts do código, então o `fea-atualizar` passa a atualizá-los.
- Subtask 42.3: Diagnóstico mostra as contas (estado e limite diário) e o espaço do rodízio; avisa quando nenhuma conta está conectada e a agenda automática não roda.
- Subtask 42.4: Simulação fiel: workers como processos, Play pela rota do painel e Drive servido localmente: 10 memes viraram 2 Shorts de 5 imagens, aprovados e agendados. A publicação depende da conta conectada; com limite 3/dia por conta, o rodízio põe 8 h entre posts.

## Task 43: Correções do diagnóstico real (21/11)
Nível: 3
Status: 1

- Subtask 43.1: O celular não atualizava: `logs/status/buscador.json` era versionado e mudava nos commits; o worker do celular também escreve nele, então o `git pull --ff-only` do `fea-atualizar` recusava e saía. Workers ficaram 10 versões atrás (PR #17) e o banco na 0009. Arquivo fora do Git; instalador e `fea-atualizar` agora ficam iguais ao main com `fetch` + `reset --hard` (`.env`, logs e venv não são versionados e ficam).
- Subtask 43.2: Drive percorre subpastas (largura primeiro, até 200 pastas, com paginação no cursor; cursor antigo continua valendo). "Testar conexão" conta a pasta inteira.
- Subtask 43.3: Música aleatória sem músicas não trava o render: sai sem música.
- Subtask 43.4: "Autorizar tudo" agenda sozinho mesmo com a agenda marcada como manual.
- Subtask 43.5: Reposição de estoque espera 30 min depois de uma busca que não achou nada (antes disparava uma por minuto).
- Subtask 43.6: Drive lista tudo da pasta (sem filtro de tipo no Google): atalhos para imagem/vídeo entram (baixa o destino) e arquivos de tipo genérico são reconhecidos pela extensão.
- Subtask 43.7: Imagens salvas com nome errado (caso real: memes salvos como `.txt`, que o Drive marca como `text/plain`) são reconhecidas pelo conteúdo: lê só os primeiros 32 bytes e confere a assinatura (JPEG, PNG, WebP, GIF, BMP, HEIC/AVIF, MP4/MOV, WebM).
- Subtask 43.8: O que fica de fora aparece contado por tipo no "Testar conexão" e no motivo de parada da busca; o Diagnóstico mostra os envios (estado, próximo horário, motivo).

## Task 36: Isolamento reforçado (fase 2)
Nível: 4
Status: -1

- Subtask 36.1: Papel de banco por operação com Row-Level Security nas tabelas com `operation_id`.
- Subtask 36.2: Credenciais por operação (chaves de fontes e contas separadas por ambiente).
- Subtask 36.3: Banco ou armazenamento próprio para operações que pedirem isolamento adicional.

## Task 37: Escala e observabilidade (futuro)
Nível: 3
Status: -1

- Subtask 37.1: Vários servidores: `infra_servers` já existe; atribuir operações a servidores e um agente por VPS.
- Subtask 37.2: Prometheus e Grafana opcionais, quando a VPS tiver memória sobrando.
- Subtask 37.3: Avaliar Redis/BullMQ só se a fila no Postgres virar gargalo (medido).

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
- Subtask 29.16: R2 só dentro da franquia grátis: trava em 80% por padrão (decidido, ajustável no Dashboard).
- Subtask 29.15: Tentativas automáticas do render: **2** (padrão do preset, `max_retries`); permissão do áudio substituto: campo no preset (decidido, ajustável).

---

## Fora desta versão

Vários usuários com papéis, fair scheduling entre operações, alertas proativos, custo por vídeo, timeline e editor manual, thumbnail personalizada, rastreamento de rostos e objetos, legendas automáticas, cortes inteligentes, construtor de máscaras, remoção de marca d'água de terceiros.
