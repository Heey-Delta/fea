# Editor Automático de Vídeos — Nível 1

Versão de referência: 1.0 (especificação enviada pelo usuário), adaptada ao projeto.
Complementa a Especificação da Ferramenta v2.1 (https://claude.ai/artifact/GHvbjsWudPNWXgXHyUyEz5). Onde houver conflito, a seção 19 lista o que precisa de decisão.

---

## 0. Ajustes em relação à especificação original

- **Não há área de edição.** Nenhuma tela de timeline, ajuste visual ou edição manual. Tudo é definido por configuração (presets), de forma padronizada.
- **Pré-visualização vira "Testar preset":** gera um render de amostra com um vídeo de exemplo e mostra o resultado e o relatório de QC. O resultado não é editável.
- **Módulo modular por rede social.** O motor é genérico. Cada rede social é um perfil próprio, com seus padrões, limites e regras. A primeira rede é o **YouTube Shorts**.
- **Sem construtor de máscara**, como na especificação original.

---

## 1. Objetivo

Motor de edição automatizada, integrado à plataforma, que recebe vídeos originais e aplica um preset da operação para garantir padrão visual e técnico consistente em todos os vídeos da operação.

O editor executa, sem intervenção manual por vídeo:

- Análise técnica dos originais.
- Padronização de proporção, resolução e FPS.
- Enquadramento conforme o modo configurado.
- Aplicação de máscara PNG sobreposta.
- Inserção de textos e elementos gráficos.
- Configurações de áudio.
- Conversão, exportação e verificação técnica.
- Armazenamento e registro do processamento.

Cada operação tem seu próprio **preset**. O motor é compartilhado por todas as operações.

---

## 2. Escopo do Nível 1

Incluído:

- Padronização de vídeo.
- Enquadramento configurável (3 modos).
- Importação e aplicação de máscaras PNG.
- Posicionamento de textos e logotipos por regras fixas.
- Elementos gráficos estáticos.
- Tratamento básico de áudio.
- Renderização automática e processamento em lote.
- Gerenciamento de presets versionados.
- Controle de qualidade.
- Histórico e versionamento.
- Integração com as filas da plataforma.

Fora do Nível 1:

- Rastreamento de rostos ou objetos.
- Enquadramento inteligente por IA.
- Legendas automáticas por reconhecimento de voz.
- Identificação automática de cenas.
- Cortes inteligentes e efeitos baseados em conteúdo.
- Construtor gráfico de máscaras.
- Editor manual com timeline.
- Detecção de áreas livres no vídeo.

---

## 3. Arquitetura modular

```
core/                    motor genérico (sem nenhum código de rede)
  pipeline               orquestra as etapas
  analise                ffprobe
  enquadramento          3 modos
  mascara                importação, validação, sobreposição
  elementos              textos (Pillow) e imagens
  audio                  preservar, remover, substituir, volume, fades
  render                 FFmpeg
  qc                     controle de qualidade
  armazenamento          originais, renders, máscaras (local; R2 depois)

networks/                um pacote por rede social
  youtube_shorts/        primeiro perfil
  tiktok/                futuro
  instagram_reels/       futuro
```

### 3.1 Perfil de rede (`NetworkProfile`)

Cada perfil informa:

- `id` e nome.
- **Saída padrão:** proporção, resolução, FPS, codecs, formato, pixel format.
- **Restrições:** duração máxima, tamanho máximo de arquivo, formatos aceitos.
- **Regras de QC específicas** da rede.
- **Limites de metadados:** título, descrição, hashtags.
- **Capacidades:** agendamento nativo, rascunho, publicação direta.
- **Adaptador de publicação** (Task 20 do `tasks.md`).

### 3.2 Regras de uso

- A operação escolhe **um** perfil de rede.
- O preset pode alterar parâmetros **dentro** das restrições do perfil.
- Preset fora das restrições é recusado **ao salvar**, não ao renderizar.
- O core nunca importa código de rede. Os perfis dependem do core, nunca o contrário.
- Adicionar uma rede nova é criar uma pasta em `networks/`, sem mudar o motor.

---

## 4. Perfil inicial: YouTube Shorts

- Proporção 9:16, vertical.
- Resolução 1080 × 1920.
- MP4, H.264, AAC, 30 FPS, yuv420p.
- **Duração máxima:** confirmar na documentação atual do YouTube antes de implementar. A v2.1 não define este limite.
- **Título e descrição:** limites a confirmar na documentação atual.
- **Cota de upload:** diária por projeto Google, tratada no adaptador (Task 20 do `tasks.md`).

---

## 5. Padrão de saída

Valores padrão do perfil, configuráveis por preset dentro das restrições do perfil:

| Parâmetro | Padrão |
|---|---|
| Proporção | 9:16 |
| Resolução | 1080 × 1920 |
| FPS | 30 |
| Formato | MP4 |
| Codec de vídeo | H.264 |
| Codec de áudio | AAC |
| Pixel format | yuv420p |
| Orientação | Vertical |

Todo vídeo de saída segue esse padrão. Originais horizontais, verticais ou quadrados são aceitos.

---

## 6. Enquadramento (3 modos)

Definido no preset.

**Modo A — Preencher.** O vídeo ocupa toda a área. Mantém a proporção original, corta o excesso e não deixa espaços vazios. Configurável: posição do corte (centro, topo, base).

**Modo B — Ajustar.** O vídeo original inteiro é redimensionado proporcionalmente e centralizado. Sobras ficam com a cor de fundo configurada.

**Modo C — Fundo desfocado.** Uma camada de fundo é gerada a partir do próprio vídeo, ampliada até preencher a tela e desfocada. O vídeo original, redimensionado proporcionalmente, fica centralizado sobre esse fundo. Nenhum conteúdo original é cortado. Configurável: intensidade do desfoque.

---

## 7. Máscaras PNG

### 7.1 Conceito

A máscara é uma imagem gráfica sobreposta ao vídeo, em camada superior. O sistema **não reconstrói** o vídeo para criar a máscara.

Composição final: camada de vídeo → máscara PNG → textos e elementos configurados.

### 7.2 Criação e importação

- As máscaras são criadas fora da plataforma e importadas.
- Formato aceito: PNG, de preferência com canal alfa.
- Cada operação pode ter sua própria máscara.

Na tela de configuração da operação é possível: selecionar e enviar o PNG, visualizar, ver resolução, proporção e transparência, associar à operação, substituir e consultar versões anteriores.

### 7.3 Validação

Verifica: integridade do arquivo, formato PNG, dimensões, canal de transparência, compatibilidade com a resolução de saída e proporção.

- Arquivo corrompido ou inválido: **bloqueia** o uso.
- Dimensão ou proporção incompatível: **aviso** exibido antes de usar.

### 7.4 Posicionamento e aparência

| Parâmetro | Padrão |
|---|---|
| Posição horizontal | 0 |
| Posição vertical | 0 |
| Largura | 100% da saída |
| Altura | 100% da saída |
| Escala | 100% |
| Opacidade | 100% |
| Alinhamento | centro |

Quando a proporção da máscara não bate com a saída, a máscara é ajustada preservando a proporção, conforme a configuração.

### 7.5 Versionamento

- Cada alteração na máscara gera nova versão (`mask_versions`), com checksum.
- Cada render guarda a `mask_version_id` usada.
- Alterações futuras não modificam renders já produzidos.

---

## 8. Textos e elementos gráficos

### 8.1 Recursos

- Texto fixo.
- Texto variável, incluindo o título recebido do módulo de metadados (`{titulo}`).
- Logotipo.
- Marca d'água própria.
- Imagens adicionais e elementos gráficos estáticos (PNG).

### 8.2 Como o texto é composto

O texto é desenhado em PNG pelo **Pillow**, com quebra de linha, contorno, sombra e alinhamento. Esse PNG é sobreposto pelo **FFmpeg** com as demais camadas. Isso dá controle de quebra de linha, que o `drawtext` do FFmpeg não oferece bem.

### 8.3 Configurações de texto

Conteúdo, fonte, tamanho, cor, contorno, sombra, alinhamento, posição horizontal e vertical, largura máxima, altura máxima.

### 8.4 Posições

Predefinidas: superior, inferior, central. Também **personalizada** (coordenadas).

Os textos respeitam a **margem de segurança** definida no preset. Se o texto estourar largura ou altura máximas, gera aviso.

### 8.5 Elementos (logotipo, marca d'água, imagens)

Cada elemento tem: posição (predefinida ou personalizada), escala e opacidade.

Não há identificação inteligente de áreas livres. Posições são sempre regras fixas.

---

## 9. Áudio

| Opção | Efeito |
|---|---|
| Preservar | mantém o áudio original |
| Remover | exporta sem áudio |
| Substituir | usa um arquivo de áudio configurado |

Ajustes:

- Volume do áudio original ou substituto.
- Normalização de loudness.
- Fade-in e fade-out (em segundos).

A saída é AAC quando há faixa de áudio.

**Direitos:** o áudio substituto precisa ter permissão de uso registrada no preset. Uso de músicas respeita os direitos de uso e as regras das plataformas.

**Aviso:** se o preset exige áudio e o original não tem faixa de áudio, o QC emite aviso (não bloqueia), a menos que o preset marque como obrigatório.

---

## 10. Presets

### 10.1 Estrutura

Cada operação tem um preset. Ele fica no JSON versionado da operação (`operation_configs`) e contém:

- **Identificação:** nome, descrição, versão, status.
- **Perfil de rede** escolhido.
- **Vídeo:** proporção, resolução, FPS, codec, formato, modo de enquadramento, configuração de fundo.
- **Máscara:** referência ao `mask_asset`, versão, posição, largura, altura, escala, opacidade.
- **Textos:** conteúdo, fonte, tamanho, cor, contorno, posição, alinhamento, margens.
- **Elementos:** logotipo, marca d'água, imagens adicionais, posições, escalas, opacidades.
- **Áudio:** preservar, remover ou substituir; arquivo; volume; normalização; fades.
- **Exportação:** formato, codec, qualidade, FPS, resolução.

### 10.2 Ações

Salvar, atualizar (gera nova versão), duplicar, ativar, consultar histórico e **testar** (render de amostra).

### 10.3 Regras

- Toda alteração gera nova versão. Versões antigas nunca mudam.
- Execução iniciada guarda **snapshot** da configuração usada. Alterar o preset depois não afeta essa execução.
- Cada render registra `preset_version_id` e `mask_version_id`.

### 10.4 Configuração sem editor

O preset é configurado por formulário agrupado em seções, com validação contra o perfil de rede. Não há timeline, arrastar elementos nem prévia editável. Quem quiser ver o efeito usa **Testar preset**.

---

## 11. Pipeline de processamento (12 etapas)

| # | Etapa | Módulo | Task (tasks.md) |
|---|---|---|---|
| 1 | Recebimento: identifica operação, item e preset | pipeline | 10 |
| 2 | Análise com ffprobe | analise | 10 |
| 3 | Carrega preset e grava snapshot | pipeline | 10, 15 |
| 4 | Enquadramento | enquadramento | 11 |
| 5 | Padronização (resolução, FPS, formato) | render | 11 |
| 6 | Máscara PNG | mascara | 12 |
| 7 | Textos e elementos gráficos | elementos | 13 |
| 8 | Áudio | audio | 14 |
| 9 | Renderização do arquivo final | render | 10, 3 |
| 10 | Controle de qualidade | qc | 17 |
| 11 | Armazenamento e histórico | armazenamento | 2, 10 |
| 12 | Encaminhamento à aprovação | pipeline | 18 |

---

## 12. Processamento em lote

- Cada vídeo é uma tarefa independente, com `task_id`, `operation_id`, `execution_id`, `content_id`, `video_id`, `preset_id`, `preset_version`, status, datas, `retry_count` e `error_message`.
- Os estados da tarefa de edição são mapeados para os estados do item da v2.1:

| Estado do editor | Estado do item (v2.1) |
|---|---|
| Aguardando | `eligible` (fila de render) |
| Em análise | `rendering` (etapa de análise) |
| Em processamento / Renderizando | `rendering` |
| Validando | `rendering` (etapa de QC) |
| Concluído | `awaiting_approval` |
| Falhou | `needs_fix` |
| Cancelado | cancelado pela execução |

- Workers compartilhados. A quantidade de tarefas simultâneas é configurável.
- Falha em um vídeo não interrompe os demais.
- Reprocessamento manual apenas dos vídeos com falha.
- Retry automático apenas para erro de **processo** (não de conteúdo). Limite de tentativas: configurável; proposta inicial de 2.

---

## 13. Controle de qualidade

### 13.1 Verificações

Arquivo existe; abre; não está corrompido; resolução, proporção, FPS, codec e formato corretos; duração válida; áudio conforme configuração; máscara aplicada; arquivo final armazenado.

### 13.2 Impeditivo ou aviso

| Impeditivo (bloqueia) | Aviso (não bloqueia) |
|---|---|
| Arquivo não existe ou não abre | Preset exige áudio e o original não tem |
| Corrompido | Máscara com dimensão ou proporção diferente |
| Resolução, proporção, FPS, codec ou formato errados | Texto estourou a largura ou altura máxima |
| Duração inválida | Duração próxima do limite do perfil |
| Máscara configurada e não aplicada | |
| Arquivo final não armazenado | |

### 13.3 Quando falha

1. Registra o erro em `events` e no relatório de QC.
2. Marca a tarefa como falha.
3. Preserva o original.
4. Permite reprocessamento.
5. **Não encaminha** o arquivo à aprovação.

Avisos não impedem o encaminhamento, mas aparecem na fila e no relatório.

---

## 14. Armazenamento e versionamento

Preservar sempre:

- Vídeo original.
- Vídeo renderizado.
- Máscara PNG usada e sua versão.
- Preset usado e sua versão.
- Configurações de edição (snapshot).
- Metadados e histórico de processamento.
- Relatório de QC.

Regras:

- O editor **nunca sobrescreve** originais.
- Cada render gera registro próprio.
- Deve ser possível saber exatamente quais configurações produziram cada vídeo.

Organização no storage:

```
operations/{op}/items/{item}/original.*
operations/{op}/items/{item}/renders/{versão}.mp4
operations/{op}/masks/{mask}/{versão}.png
```

Armazenamento local no início, com adaptador para Cloudflare R2 (ver seção 19).

---

## 15. Integração com a plataforma

Fluxo:

1. Operação inicia execução.
2. Sistema coleta conteúdos.
3. Conteúdos passam por validação (dedup, permissão, classificação).
4. Elegíveis vão para edição.
5. Motor consulta o preset da operação.
6. Vídeos são processados automaticamente.
7. Resultados passam pelo QC.
8. Válidos vão à fila de aprovação.
9. Usuário revisa e aprova.
10. Aprovados seguem para distribuição.

Vínculos de cada vídeo: operação, execução, conteúdo original, arquivo editado, preset e versão, máscara e versão.

A fila individual da operação e a fila geral exibem os mesmos registros persistidos.

---

## 16. Segurança e confiabilidade

- Originais preservados.
- Arquivos importados validados antes do uso.
- Arquivo inválido nunca é usado.
- Alterações de preset e máscara registradas em `events`.
- Configurações versionadas.
- Identificadores únicos por tarefa.
- Renderização não duplicada (chave de idempotência por item e versão de configuração).
- Reprocessamento controlado e registrado.
- Erros e tentativas registrados.
- Alterações de preset nunca afetam tarefas já iniciadas.

---

## 17. Princípios

Prioridades, nesta ordem: consistência, previsibilidade, velocidade, processamento em lote, baixo custo operacional, reprodutibilidade, facilidade de manutenção.

O motor é baseado em regras fixas. Não tenta entender o conteúdo visual. Posição de máscara, texto e enquadramento vêm do preset e do modo escolhido.

A arquitetura permite recursos inteligentes no futuro sem reconstruir o motor básico.

---

## 18. Critérios de aceitação do Nível 1

1. Recebe vídeos de resoluções diferentes.
2. Aceita horizontais, verticais e quadrados.
3. Aplica os três modos de enquadramento.
4. Converte para o padrão configurado.
5. Importa máscaras PNG.
6. Valida os PNG.
7. Aplica máscaras sobrepostas.
8. Configura posição e escala da máscara.
9. Configura opacidade.
10. Insere textos automaticamente.
11. Insere logotipos e elementos gráficos.
12. Executa as configurações de áudio.
13. Salva presets por operação.
14. Versiona presets e máscaras.
15. Processa vários vídeos em lote.
16. Registra tarefas individualmente.
17. Identifica erros de renderização.
18. Permite reprocessamento.
19. Preserva os arquivos originais.
20. Encaminha à aprovação os vídeos tecnicamente válidos.

---

## 19. Decisões e conflitos a resolver

Itens que mudam o que já está na v2.1 ou que dependem de você antes de implementar.

| Tema | Especificação do editor | v2.1 | Proposta |
|---|---|---|---|
| Fila de tarefas | Redis + Celery | Postgres (`FOR UPDATE SKIP LOCKED`), sem Redis | **Decidir.** Recomendo Postgres agora, com a fila atrás de uma interface, e Celery só se medirmos gargalo. |
| Armazenamento | S3 ou R2 | Disco local, R2 depois | Disco local com adaptador. R2 quando precisar de disco fora da VPS. |
| Tabelas | 7 tabelas novas do editor | 12 tabelas | 14 tabelas: as 12 da v2.1 + `mask_assets` e `mask_versions`. Presets ficam em `operation_configs`. Logs de render vão para `events`. |
| Editor | Pré-visualização e configuração | Editor com tela (REQ-UI-006) | Sem editor. Configuração por formulário e "Testar preset". Remover REQ-UI-006 da v2.1. |
| Estados | Estados próprios de tarefa | Estados do item e do envio | Mapeamento da seção 12. Nenhuma máquina extra. |
| Redes sociais | Não citado | Uma rede (YouTube) | Módulo modular por perfil de rede (seção 3). |

Também precisa de definição:

- Limite de duração e de título do YouTube Shorts (confirmar na documentação atual).
- Número de tentativas automáticas do render (proposta: 2).
- Permissão e licença de cada áudio substituto.

---

## 20. Fases de desenvolvimento

Ordem das fases da especificação, com a task correspondente no `tasks.md`:

| Fase | Escopo | Tasks |
|---|---|---|
| 1 — Fundação | FFmpeg, ffprobe, integração Python, estrutura de tarefas | 1, 3, 9, 10 |
| 2 — Padronização | Conversão, resolução, FPS, modos de enquadramento | 11 |
| 3 — Máscaras | Importação, validação, posição, escala, opacidade, sobreposição | 12 |
| 4 — Elementos gráficos | Textos, logotipos, imagens, posições | 13 |
| 5 — Áudio | Preservar, remover, substituir, volume, normalizar, fades | 14 |
| 6 — Presets | Configuração, salvar, associar à operação, versionamento | 15 |
| 7 — Renderização | Lote, workers, fila, estados e tentativas | 3, 10 |
| 8 — Controle de qualidade | Verificação, parâmetros, falhas, reprocessamento | 17 |
| 9 — Integração | Operações, filas, aprovação, histórico geral | 4, 8, 18, 25 |
