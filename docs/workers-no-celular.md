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
- `fea-painel`: painel ao vivo, em estilo brutalista. Cada worker aparece numerado, com o que está fazendo (AGUARDANDO, BUSCANDO, EDITANDO, PUBLICANDO, LIMPANDO), barra e porcentagem, e uma etiqueta `[ OK ]` (verde), `[ERRO]` (vermelho, falha nos últimos 15 minutos) ou `[ OFF]` (desligado). Digite `/log` (ou `/log editor`) e Enter para ver os detalhes; `/voltar` ou Esc volta; `/sair` fecha. Os workers continuam rodando depois que o painel fecha.
- `fea-status`: retrato rápido, sem ficar aberto.
- `fea-desligar` / `fea-ligar`: parar e voltar.
- **Atualizar o código:** `fea-atualizar` (baixa o código novo, aplica migrações e reinicia). Os workers do celular **não se atualizam sozinhos**: depois de cada mudança na ferramenta, rode esse comando. Se o `fea-atualizar` ainda não existir, rode uma vez o comando do passo 2.
- Em Acessos → Workers, o painel mostra 4/4 no ar em cerca de 1 minuto.

## Se algo falhar
Copie as últimas linhas do erro (sem linhas com `DATABASE_URL` ou chaves) e mande ao Claude. Este instalador não foi testado num celular de verdade: é possível que alguma biblioteca precise de ajuste.

## Quando você tiver uma VPS
Não precisa desmontar nada no celular. Na VPS, cole o comando de **Acessos → Workers → Gerar comando de instalação (VPS)**. Os workers do celular percebem a plataforma ativa e param sozinhos ("migrado para a VPS"). Detalhes em `docs/plataforma.md`.

## Workers que caem sozinhos (Android)
O Android mata processos em segundo plano: tela apagada, economia de bateria e o "phantom process killer" do Android 12+. Desde a Task 42, cada worker religa sozinho em 10 s se cair, e o log registra "worker X parou (código N); religando". Para cair menos:
1. Configurações → Apps → Termux → Bateria → **Sem restrições**.
2. Deixe a notificação do Termux ativa (wake lock).
3. Android 14 ou mais novo: Opções do desenvolvedor → **Desativar restrições de processos filhos**.
4. Instalação feita antes da Task 42: rode o instalador uma vez de novo para o `fea-ligar` passar a religar os workers. Depois disso o `fea-atualizar` mantém os scripts em dia.
