# Fluxo da Operação — Blocos e Canvas

> **Atualização (Task 28):** na interface o fluxo agora são três blocos em sequência, **Pesca → Motor Editor → Publicador**, cada um com o próprio formulário. As fontes ficam dentro da Pesca; a rede social, as contas e a aprovação ficam dentro do Publicador. O JSON salvo continua sendo o grafo descrito abaixo: a tela gera os blocos internos e as ligações ao salvar. Uma operação pode publicar em mais de uma rede (YouTube Shorts, TikTok, Instagram Reels). As chaves e os logins ficam na tela **Acessos**.

Define os três grandes blocos da ferramenta e como uma operação é montada ligando blocos entre si.

Complementa a Especificação v2.1 e o `docs/editor-nivel-1.md`. Tasks correspondentes no `tasks.md`: Task 4 (canvas), Tasks 5 a 8 (Pesca), Tasks 9 a 18 (Edição), Tasks 19 a 24 (Postagem).

---

## 1. Visão geral

```
[Fonte: Upload] ──┐
                  ├──> [PESCA] ──> [EDIÇÃO] ──> [APROVAÇÃO] ──> [POSTAGEM] ──> [Conta A]
[Fonte: Reddit] ──┘        ▲            ▲                           ▲
                           │            │                           │
                           └─────── [REDE: YouTube Shorts] ────────┘
                                    (bloco de contexto, um por operação)
```

- **Fontes** alimentam a Pesca.
- **Pesca** busca, filtra e classifica conteúdo.
- **Edição** padroniza, mascara e renderiza.
- **Aprovação** é o portão humano antes da publicação.
- **Postagem** agenda e publica nas contas ligadas a ela.
- **Rede** define o perfil técnico e de metadados usado por Edição e Postagem.

Cada bloco é um módulo com entradas, saídas e configuração própria. O canvas só monta a ligação entre eles.

---

## 2. Os três blocos

### 2.1 Pesca — busca conteúdo

**Função:** buscar conteúdo nas fontes usando **tags** e **heat tags**, filtrar e classificar.

**Entrada:** fontes ligadas ao bloco.

**Saída:** itens `eligible` (ou `pending_permission`, `rejected`, `duplicate`) prontos para Edição.

**Configuração:**

| Campo | Uso |
|---|---|
| Tags | Termos de busca nos conectores que pesquisam. Também filtram: com tags configuradas, score 0 vira `rejected` ("fora do nicho"). |
| Heat tags | Termos de maior prioridade. Valem 2 pontos no score e são usadas no critério "priorizar heat tags". |
| Palavras bloqueadas | Excluem o item. |
| Quantidade X | Meta de elegíveis por execução (ver Task 6). |
| Orçamento de busca | Máximo de itens brutos examinados. |
| Critério | Mais recentes (padrão) ou priorizar heat tags. |
| Duração e mídia | `max_duration_s` e `accepted_media`. |

**Como busca:** cada conector declara se suporta busca por tags. Reddit pesquisa por tags e heat tags na API oficial. Upload manual não pesquisa: as tags funcionam só como filtro.

**Estados visíveis:** encontrado, em validação, pendente de autorização, elegível, rejeitado, duplicado.

### 2.2 Edição — padroniza, mascara e renderiza

**Função:** transformar cada item elegível no vídeo final padronizado, com máscara, textos, áudio e QC.

**Entrada:** itens `eligible` da Pesca.

**Saída:** renders que passaram no QC (`awaiting_approval`) ou que falharam (`needs_fix`).

**Configuração:** é o **preset** da operação (ver `docs/editor-nivel-1.md`):

- Perfil de rede (vem do bloco Rede).
- Padrão de saída: proporção, resolução, FPS, codecs.
- Modo de enquadramento: preencher, ajustar ou fundo desfocado.
- Máscara PNG: posição, escala, opacidade.
- Textos e elementos: logotipo, marca d'água, textos fixos e variáveis.
- Áudio: preservar, remover ou substituir; volume, normalização, fades.
- Títulos: Markov com fallback (ver Task 16).

**Sem área de edição visual.** O bloco é configurado por formulário. A única prévia é "Testar preset".

### 2.3 Postagem — agenda e publica

**Função:** agendar e publicar os vídeos aprovados nas contas ligadas.

**Entrada:** renders aprovados (ver Aprovação).

**Saída:** envios `published`, `scheduled_platform`, `failed`, `skipped` etc.

**Configuração:**

| Campo | Uso |
|---|---|
| Contas | Uma ou mais, ligadas ao bloco por arestas. Uma tarefa por vídeo × conta. |
| Intervalo (min) | Espaçamento entre envios por conta. 0 libera tudo, respeitando limites. |
| Primeira publicação imediata | Liga ou desliga o primeiro envio imediato. |
| Início | Data e hora, quando "imediata" está desligada. |
| Janela | Horário permitido de publicação, por conta. |
| Título de publicação | Vem de Edição, com possibilidade de sobrescrever por plataforma. |
| Descrição e tags | Templates e tags por plataforma. |

---

## 3. Blocos de apoio

- **Fonte** (um bloco por fonte). Ex.: `Fonte: Upload`, `Fonte: Reddit r/...`. Carrega `permission_note` (obrigatório, REQ-UI-004).
- **Rede** (um por operação). Escolhe o perfil de rede. Não tem saída; alimenta Edição e Postagem.
- **Aprovação** (um por operação). Portão humano. Configura se a aprovação é obrigatória e os critérios para aprovação automática (campo `approval.required`; automática fica para depois, Task 29.11).
- **Conta** (um por conta conectada). Liga-se a Postagem. Carrega `daily_limit` e fuso.

---

## 4. Canvas de criação de operação

### 4.1 O que é

Uma tela onde os blocos aparecem como cartões. Cada bloco tem portas de entrada (à esquerda) e saída (à direita). Ligar uma saída a uma entrada cria uma aresta, que define o fluxo.

O canvas configura o fluxo. **Não edita vídeo.** Não há timeline, arrastar elementos sobre o vídeo nem prévia editável.

### 4.2 Como montar

1. Criar operação com nome.
2. Adicionar blocos (botão "+" ou arrastar da paleta: Fonte, Pesca, Edição, Aprovação, Postagem, Rede, Conta).
3. Clicar em um bloco abre o painel de configuração em formulário, do lado direito.
4. Ligar portas: arrastar da saída de um bloco até a entrada de outro.
5. Validar. Erros aparecem marcados nos blocos.
6. Salvar. Cada salvamento gera uma nova versão do grafo.

### 4.3 Tipos de porta e regras de ligação

| Porta de saída | Só liga a entrada de | Dados |
|---|---|---|
| Fonte | Pesca | itens brutos |
| Pesca | Edição | itens elegíveis |
| Edição | Aprovação | renders validados |
| Aprovação | Postagem | renders aprovados |
| Rede | Edição, Postagem | perfil |
| Conta | Postagem | conta |

Ligações fora dessa tabela são recusadas na hora, com mensagem explicando o motivo.

### 4.4 Regras de validação (antes de salvar como ativa)

- Pelo menos uma Fonte ligada a uma Pesca.
- Pesca → Edição → Aprovação → Postagem, nessa ordem, sem pular etapas.
- Exatamente uma Rede por operação, ligada a Edição e a Postagem.
- Pelo menos uma Conta ligada à Postagem.
- Sem ciclos.
- Fonte sem `permission_note` gera aviso, não bloqueia (os itens vão para `pending_permission`).
- Rascunho pode ter erros. Ativa não.

### 4.5 Grafo como configuração

O canvas salva um JSON versionado em `operation_configs`:

```json
{
  "nodes": [
    {"id": "fonte_reddit", "type": "source", "config": {"reference": "r/..."}},
    {"id": "pesca", "type": "fishing", "config": {"tags": [...], "heat_tags": [...], "target_x": 10}},
    {"id": "edicao", "type": "edit", "config": {"preset": {...}}},
    {"id": "aprovacao", "type": "approval", "config": {"required": true}},
    {"id": "postagem", "type": "publish", "config": {"interval_min": 10, "first_immediate": false}},
    {"id": "rede", "type": "network", "config": {"profile": "youtube_shorts"}},
    {"id": "conta_a", "type": "account", "config": {"account_id": "..."}}
  ],
  "edges": [
    {"from": "fonte_reddit", "to": "pesca"},
    {"from": "pesca", "to": "edicao"},
    {"from": "edicao", "to": "aprovacao"},
    {"from": "aprovacao", "to": "postagem"},
    {"from": "conta_a", "to": "postagem"}
  ]
}
```

Consequências:

- Versionar o canvas é versionar o JSON. Não precisa de tabela extra.
- Cada execução guarda snapshot do grafo. Alterar a operação depois não muda execuções em andamento.
- O motor executa o grafo na ordem das arestas, chamando o módulo de cada tipo de bloco.

### 4.6 Modularidade

- O canvas conhece tipos de bloco, não implementações.
- Um tipo novo de bloco é um módulo novo, com schema de configuração e portas. O canvas o exibe sem mudança estrutural.
- Um conector novo de fonte aparece como novo tipo de Fonte.
- Uma rede nova é um perfil novo (ver `docs/editor-nivel-1.md`, seção 3).

### 4.7 Operação arquivada

Canvas em modo somente leitura. Pode duplicar a operação para criar nova versão do fluxo.

---

## 5. Fluxo de execução

1. O usuário clica em Play em uma operação ativa (ver Task 6).
2. A Pesca busca nas fontes e produz itens elegíveis até X.
3. Cada item elegível vira uma tarefa de Edição.
4. A Edição renderiza e o QC valida. Válidos vão à fila de aprovação.
5. O usuário aprova e escolhe o que distribuir.
6. A Postagem agenda e publica por conta, conforme intervalo, janela e limites.

Pesca e Edição rodam automaticamente. Postagem só roda com ação explícita do usuário (Nova publicação, Task 21).

---

## 6. Decisões

| Tema | Proposta | Confirmar |
|---|---|---|
| Canvas vs. "sem editor" | O canvas configura fluxo, não edita vídeo. Compatível com a decisão de não ter editor visual. | Sim? |
| Aprovação como bloco | Bloco próprio, entre Edição e Postagem. | Sim? |
| Rede como bloco | Bloco de contexto, um por operação, ligado a Edição e Postagem. | Sim? |
| Uma Rede por operação | Simplifica. Operação que publica em duas redes = duas operações. | Sim? |
| Fontes com busca por tags | Conector declara `search(tags, cursor)`, além de `fetch`. | Sim? |
| Formato do grafo | JSON versionado em `operation_configs`, sem tabelas de bloco. | Sim? |
