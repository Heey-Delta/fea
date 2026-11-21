# Workers no celular Android (Termux)

Caminho gratuito para quem não tem computador sobrando. Serve para testar o fluxo e gravar a demonstração da auditoria. Para operar todo dia, uma VPS ou um computador é mais firme (`docs/rumos.md`).

Estimativa, não medida: a edição de um vídeo de 30 s leva de 1 a 3 minutos de CPU, e o consumo de internet fica entre 20 e 100 MB por vídeo.

## Antes
- Android (iPhone não serve).
- Termux do **GitHub** (`github.com/termux/termux-app/releases`) ou do **F-Droid**. Nunca o da Play Store. Não misture origens.
- Wi-Fi e carregador. Uns 3 GB livres.

## 1 · Baixar a configuração
1. No navegador do celular, entre na ferramenta, em Acessos → Workers.
2. Toque em **Baixar .env (meu computador)**. O arquivo `fea-workers.env` vai para Downloads. Ele dá acesso ao banco: o instalador o move para dentro do Termux e apaga o original.

## 2 · Instalar
No Termux:
```
pkg install -y curl
bash <(curl -fsSL https://fea-rho.vercel.app/static/instalar-termux.sh)
```
- Aceite a permissão de armazenamento quando o Android pedir.
- Em algum momento ele mostra uma chave `ssh-ed25519`. Cole em **GitHub → Heey-Delta/fea → Settings → Deploy keys → Add deploy key** (título `Celular`, sem permissão de escrita) e volte ao Termux para teclar Enter.
- A primeira vez demora (10 a 40 minutos): o pydantic é compilado no celular. Deixe a tela ligada e o carregador conectado.

## 3 · Evitar que o Android derrube
1. Configurações do Android → Apps → Termux → Bateria → **Sem restrições**.
2. Deixe a notificação do Termux (wake lock) ativa.
3. Mantenha o celular no carregador, em lugar fresco.

## 4 · Dia a dia
- `fea-painel`: painel ao vivo. Cada worker aparece com o que está fazendo (Aguardando, Buscando, Editando, Publicando, Limpando), barra e porcentagem, e uma bolinha **verde** (no ar) ou **vermelha** (desligado ou com falha nos últimos 15 minutos). Digite `/log` (ou `/log editor`) e Enter para ver os detalhes; `/voltar` ou Esc volta; `/sair` fecha. Os workers continuam rodando depois que o painel fecha.
- `fea-status`: retrato rápido, sem ficar aberto.
- `fea-desligar` / `fea-ligar`: parar e voltar.
- **Atualizar o código:** `fea-atualizar` (baixa o código novo, aplica migrações e reinicia). Os workers do celular **não se atualizam sozinhos**: depois de cada mudança na ferramenta, rode esse comando. Se o `fea-atualizar` ainda não existir, rode uma vez o comando do passo 2.
- Em Acessos → Workers, o painel mostra 4/4 no ar em cerca de 1 minuto.

## Se algo falhar
Copie as últimas linhas do erro (sem linhas com `DATABASE_URL` ou chaves) e mande ao Claude. Este instalador não foi testado num celular de verdade: é possível que alguma biblioteca precise de ajuste.
