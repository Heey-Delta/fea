# Auditoria da API do YouTube (formulário "Audit and Quota Extension")

Sem a auditoria, os vídeos enviados pela API sobem como **privados**. O formulário é preenchido por você, em inglês, com os dados abaixo. Dados pessoais (nome, endereço, e-mail) não estão aqui: são os seus, reais.

Formulário: pesquise "YouTube API Services Audit and Quota Extension Form".

## Antes de enviar

1. Workers no ar (Acessos → Workers: 4/4) e canal conectado (Acessos → YouTube: conectada).
2. Um upload de teste concluído (o vídeo aparece como privado no YouTube Studio).
3. O screencast gravado (roteiro abaixo) e subido como **não listado**.
4. A variável `CONTACT_EMAIL` definida na Vercel: é o contato que aparece nas páginas públicas. Sem ela, as páginas dizem "pelo contato informado no cadastro", e a Google pode estranhar. É decisão sua publicar um e-mail; use um que você aceite expor.

## Respostas

| Campo | Resposta |
|---|---|
| Reason | Complete a compliance audit to request for additional quota |
| Applying as | An individual user |
| Organization / Parent company | `self` |
| Primary website | `https://fea-rho.vercel.app/sobre` |
| Category | Creator Tools and Services |
| Size / Type | Independent Developer/Sole Proprietor |
| Monetization | Free service (we do not charge users) |
| Partner manager | No, I do not have a Google representative |
| Content Owner ID, Ads Customer ID | em branco |
| Target audience | Individual Content Creators; Other: `Only the applicant (single user)` |
| API Client name | `fea9001` (não contém "YouTube") |
| Primary access URL | `https://fea-rho.vercel.app` |
| Login URL | `https://fea-rho.vercel.app/login` |
| Privacy policy | `https://fea-rho.vercel.app/privacidade` |
| Terms | `https://fea-rho.vercel.app/termos` |
| Publicly accessible | No (login restrito a uma conta) |
| Project number | `379992440437` (confira no card Welcome do console) |
| Use cases | Video Uploading & Account Management; Analytics & Reporting |
| Google sign-in (OAuth) | Yes |
| Endpoints | `videos.insert`, `videos.list`, `channels.list` |
| Quota | No change / Default quota (10k) |
| `videos.insert` per day | `8000` (5 envios × 1.600 unidades; confira o custo no calculador de quota) |

### Textos

**Describe your organization's work as it relates to YouTube**

```
I'm an independent creator running my own YouTube channel focused on short vertical videos (Shorts). I built a small personal tool, used only by me, to streamline my publishing workflow: it formats videos I own or have explicit permission to use into the vertical Shorts format, uploads them to my own channel via OAuth, sets titles, descriptions and tags, and reads basic statistics (views, likes, comments) of my own uploads to track performance. The tool is not offered to other users and does not access any channel other than mine.
```

**Value you provide**

```
The tool saves time in my own publishing workflow. I prepare short vertical videos I own or have explicit permission to use, and it handles the repetitive steps: formatting to the vertical Shorts format, uploading to my channel through OAuth, filling in titles, descriptions and tags, and reading basic statistics (views, likes, comments) of my own uploads so I can see what performs well. It is a single-user tool and does not provide a service to third parties.
```

**API Client overview (Section 4)**

```
Single-user personal tool. Only I use it, with my own Google account, to upload Shorts to my own YouTube channel. Auth is OAuth 2.0 with the scopes youtube.upload and youtube.readonly. Endpoints used: videos.insert, videos.list, channels.list. Access tokens are encrypted at rest. The tool does not show or share YouTube data with other users, does not store viewer data, and does not use the API for advertising.
```

**Expected API usage volume**

```
5 video uploads per day (videos.insert) plus a few reads per day (videos.list, channels.list) for my own videos.
```

**Quota justification (`videos.insert`)**

```
Single-user personal tool. I upload up to 5 short vertical videos per day, each one I own or have explicit permission to use, to my own YouTube channel. 5 uploads cost about 8,000 units (1,600 per videos.insert), which fits in the default 10,000 daily quota. I am not requesting a quota increase; the purpose of this audit is to lift the restriction that makes uploads from unaudited API projects private.
```

**Demo account (Section 4):** deixe usuário e senha em branco ou `N/A`.

```
No demo account is available: the tool is a single-user internal application, and its login is restricted to the owner's GitHub account. Please see the end-to-end screencast provided in Section 6, which shows the OAuth consent, the connected channel, and a Shorts upload with its statistics.
```

## Arquivos

Formato JPEG ou PNG, com no mínimo 1280×720, texto legível e a barra de endereço visível. Um arquivo por campo, até 10 MB. Cubra chaves, tokens e e-mails pessoais.

| Campo | O que enviar |
|---|---|
| Privacy policy | Print de `/privacidade` mostrando a seção "YouTube API Services" |
| Homepage | Print de `/sobre` com o link da política visível (o site não tem a marca do YouTube, não invente) |
| Terms | Print ou PDF de `/termos` |
| OAuth flow | Print da tela de consentimento do Google com os dois escopos |
| Upload interface | Print do bloco Publicação com o canal escolhido |
| Dashboard | Print de Publicações com as estatísticas de um vídeo |
| Architecture diagram | `architecture-diagram.png` (enviado no chat) |
| User flow diagram | `user-flow-diagram.png` (enviado no chat) |
| Other supporting materials | Link do screencast (não listado) |

## Roteiro do screencast (2 a 4 minutos)

1. Abra `fea-rho.vercel.app/login` e entre com o GitHub.
2. Acessos → YouTube: mostre o canal conectado. Clique em Conectar conta, mostre a tela de consentimento do Google com os escopos e aceite.
3. Crie uma operação: Busca por upload (um vídeo seu), Edição vertical, Publicação no canal.
4. Execute, aprove o vídeo em Aprovação e espere publicar.
5. Mostre o vídeo no YouTube Studio e a tela Publicações com as estatísticas.
6. Mostre o botão de desconectar a conta (Revogar).

Enquanto o projeto não for auditado, o vídeo sobe como privado. Diga isso em voz alta ou em legenda no vídeo, para o revisor entender.

## Sobre a fonte de vídeos

A auditoria afirma que você só publica vídeos seus ou com permissão. Se a fonte for o Reddit, cada comunidade ou autor precisa ter autorizado o reuso e isso fica registrado na operação. Se a prática for outra, ajuste o texto do formulário antes de enviar: respostas que não batem com o uso real são motivo de reprovação e de corte do acesso.
