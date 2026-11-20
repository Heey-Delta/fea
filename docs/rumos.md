# Rumos: o essencial para começar e como crescer

Situação em 20/11/2026: o Reddit não libera app novo sem aprovação, e a Oracle exigiu CNPJ. Este documento organiza os caminhos que **não dependem** de nenhum dos dois.

## A ferramenta em quatro peças

| Peça | O que faz | Hoje | Sem bloqueio para começar |
|---|---|---|---|
| **Entrada (fonte)** | De onde vêm os vídeos | Upload manual, Google Drive, Reddit (bloqueado), X (pago) | **Google Drive** ✓ |
| **Processamento (workers)** | Busca, edita (FFmpeg), publica e limpa | Instalador para VPS | **Seu computador com Docker Desktop** ✓ |
| **Armazenamento** | Guarda os arquivos entre as etapas | Cloudflare R2 com teto de uso | ✓ pronto |
| **Saída (publicação)** | Onde os vídeos são publicados | YouTube Shorts, TikTok, Instagram Reels | **YouTube** ✓ (privado até a auditoria) |

Com as peças marcadas ✓, a primeira versão já roda de ponta a ponta. O vídeo cai na pasta do Drive, o worker no seu computador baixa e edita, e o YouTube publica.

Cada peça é um encaixe: um **conector** por fonte (`core/connectors/`) e um **adaptador** por rede (`networks/`). Para uma plataforma nova, basta escrever um arquivo, sem mexer no resto. É isso que deixa a ferramenta adaptável.

---

## 1 · Fontes de vídeo

| Fonte | Custo | Cadastro | Situação | Observação |
|---|---|---|---|---|
| **Google Drive** (pasta) | grátis | Conta de serviço no Google Cloud, sem CNPJ e sem verificação | **Pronto** | Você ou criadores autorizados soltam vídeos na pasta. Escolhemos a conta de serviço porque a leitura do Drive pelo login comum é um escopo *restrito* e exigiria verificação do Google. |
| **Upload manual** | grátis | nenhum | Pronto | Pela própria tela da operação. |
| **Pexels** | grátis | Chave pessoal | A fazer (cerca de 1 dia) | Licença permite uso comercial sem atribuição; proíbe revender como banco de imagens. Pessoas identificáveis podem exigir autorização de imagem. |
| **Pixabay** | grátis | Chave pessoal | A fazer (cerca de 1 dia) | Uso comercial permitido. Pede crédito quando mostra resultados de busca e cache de 24 horas. Algumas músicas geram Content ID no YouTube. |
| **Dropbox / OneDrive** | grátis | App pessoal | A fazer | Mesma ideia do Drive, se for mais prático para quem envia os vídeos. |
| **Reddit** | grátis | Registro de app pendente | Bloqueado | Acesso público da API termina em março de 2027. |
| **X** | caro (plano pago da API) | App no portal do X | Pronto, sem uso | Só compensa com receita. |

**Não recomendado:** baixar do TikTok, do Instagram ou do YouTube. Viola os termos dessas plataformas e o que foi declarado na auditoria do YouTube.

## 2 · Onde rodar os workers

| Opção | Custo | Exige | Prós | Contras |
|---|---|---|---|---|
| **Seu computador** (Docker Desktop) | grátis | Computador com 8 GB de memória | **Pronto**, ver `docs/workers-no-computador.md` | Só roda com o computador ligado. |
| **VPS paga barata** (Hetzner, Contabo, IONOS, DigitalOcean) | a partir de cerca de US$ 5 por mês | Cartão; algumas pedem documento com foto | 24 horas; o instalador atual funciona igual | Preços mudaram em 2026; confira no site antes. 4 GB no DigitalOcean custam cerca de US$ 24. |
| **Google Cloud** | US$ 300 de crédito por 90 dias; depois, uma máquina e2-micro grátis | Conta de faturamento, com CPF/CNPJ "quando exigido por lei" | Mesma conta do YouTube | A e2-micro tem 1 GB, pouco para editar vídeo. Não confirmei se pessoa física no Brasil passa. |
| **GitHub Actions agendado** | 2.000 minutos por mês no plano Free (repositório privado) | nada | Sem servidor | Os termos proíbem usar Actions para atividade não ligada ao software do repositório. Editar e publicar vídeo provavelmente se enquadra nisso. **Não recomendado.** |
| **Oracle Free** | grátis | Pediu CNPJ no seu caso | — | Bloqueado. |

**Recomendação:** use o seu computador agora, para testar, gravar a demonstração e enviar a auditoria. Quando o volume justificar, migre para uma VPS paga de cerca de US$ 5 por mês, com o mesmo instalador.

## 3 · Onde publicar

| Rede | API oficial de vídeo | Situação na ferramenta | Bloqueio |
|---|---|---|---|
| **YouTube Shorts** | Sim (Data API v3) | **Pronto** | Vídeos privados até a auditoria. |
| **TikTok** | Sim (Content Posting API) | Pronto | Posts visíveis só para você até a revisão do app. |
| **Instagram Reels** | Sim (Instagram API with Instagram Login) | Pronto | Conta profissional. |
| **Facebook Reels** | Sim (Reels Publishing API, envio em três etapas) | A fazer | Página do Facebook e app Meta. Dá para usar o mesmo app do Instagram. |
| **Threads** | Sim (contêiner de mídia → publicar, como o Instagram) | A fazer | App Meta. |
| **Pinterest, Bluesky, LinkedIn** | Existem, mas não confirmei os detalhes atuais | Avaliar | — |
| **Kwai** | Não encontrei API pública de publicação | — | — |

### Atalho pago: API que publica em várias redes de uma vez
| Serviço | Preço (dito pelos próprios fornecedores) | O que muda |
|---|---|---|
| **Upload-Post** | plano grátis; pago a partir de cerca de US$ 16 a 24 por mês | Uma chamada publica em cerca de 11 redes. |
| **Ayrshare** | a partir de cerca de US$ 149 por mês | Mais de 14 redes, com métricas. |

Esses serviços evitam criar e aprovar um app em cada rede. Em troca, você paga uma assinatura e depende de terceiros. Dá para encaixar um deles como mais um adaptador, só para as redes que não valem o esforço próprio.

---

## Plano sugerido

**Versão de início (agora, sem custo):**
1. Workers no seu computador.
2. Fonte: pasta do Google Drive.
3. Publicação: YouTube. O teste fica privado; grave a demonstração e envie a auditoria (`docs/auditoria-youtube.md`).

**Próximos passos, em ordem de impacto:**
1. Conector **Pexels/Pixabay**: vídeos licenciados sem depender de ninguém.
2. **Facebook Reels** e **Threads**: reaproveitam o app Meta do Instagram.
3. **VPS paga** para rodar 24 horas.
4. Agregador (Upload-Post) para redes menores, se fizer sentido.

## Fontes da pesquisa
- Escopos do Drive e limite de apps não verificados: [Requesting Minimum Scopes](https://support.google.com/cloud/answer/13807380?hl=en), [Manage App Audience](https://support.google.com/cloud/answer/15549945), [Unverified apps](https://support.google.com/cloud/answer/7454865)
- Licença Pexels: [licença](https://help.pexels.com/hc/en-us/articles/360042295174-What-is-the-license-of-the-photos-and-videos-on-Pexels), [uso comercial](https://help.pexels.com/hc/en-us/articles/360042295214-Can-I-use-the-photos-and-videos-for-a-commercial-project), [API](https://www.pexels.com/api/documentation/?language=javascript)
- Licença Pixabay: [FAQ](https://pixabay.com/service/faq/), [API](https://pixabay.com/api/docs/), [termos](https://pixabay.com/service/terms/)
- VPS: [VPS Price Tracker](https://findstack.com/resources/vps-price-tracker), [Hetzner 2026](https://findstack.com/resources/hetzner-price-increase-2026), [preço por GB](https://findstack.com/resources/cheapest-vps-hosting), [Hetzner vs DigitalOcean](https://betterstack.com/community/guides/web-servers/digitalocean-vs-hetzner/)
- Google Cloud: [crédito de teste](https://cloud.google.com/free-trial/?hl=pt-br), [limites do nível gratuito](https://docs.cloud.google.com/free/docs/always-free-usage-limits?hl=pt-br)
- GitHub Actions: [cobrança](https://docs.github.com/en/billing/concepts/product-billing/github-actions), [termos de produtos adicionais](https://docs.github.com/en/site-policy/github-terms/github-terms-for-additional-products-and-features)
- Meta: [Reels Publishing API](https://developers.facebook.com/docs/video-api/guides/reels-publishing), [Threads Posts](https://developers.facebook.com/documentation/threads/posts)
- Agregadores: [Upload-Post vs Ayrshare](https://www.upload-post.com/pricing-comparison), [Ayrshare](https://www.ayrshare.com/compare/upload-post-api-alternative/), [Buffer: APIs multiplataforma](https://buffer.com/resources/social-media-api-multi-platform-posting/)
