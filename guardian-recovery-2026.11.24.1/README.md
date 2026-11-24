# Guardian Recovery 2026.11.24.1

Atualizacao do monitor MySQL/MariaDB e FreeRADIUS. Mantem configuracao local, nome e Telegram, com consulta ao nome do grupo e opcao de corrigir/testar/ignorar falha de envio. Instalacao sem argumentos aplica; --dry-run simula. Use terminal SSH interativo.

## Mudancas desta versao

- Detecta a mensagem completa de fila esgotada (Something is blocking the server ... packets in the queue ... Ignoring the new request), separadamente das mensagens unfinished. Duas amostras novas consecutivas permitem recuperacao segundo as permissoes existentes; cooldown e limites por hora permanecem. Texto semelhante dentro de mensagens de autenticacao nao e classificado como fila cheia.
- Repeticao limitada da instalacao quando o processo retorna BUSY: cada tentativa termina e libera seus locks antes da espera; no maximo tres tentativas e 90 segundos acumulados de espera. Fontes desconhecidas e erros de validacao nao sao repetidos. Simulacao nao aguarda nem repete.

- Acrescenta dois hashes exatos revisados: MySQL Guardian v1.4 e Backup Guardian v1.6, e dois comandos cron exatos dessa versao. A migracao substitui os scripts antigos; nao executa seus mecanismos antigos de pkill/remocao de socket. Fontes desconhecidas continuam recusadas. Nenhum conteudo privado dos scripts foi incluido no pacote.

- Corrige a revisao do cron quando uma referencia historica comentada acompanha uma unica tarefa ativa: somente a ativa e envolvida no limite; o comentario permanece intacto. Duas tarefas ativas ou varias referencias pausadas sem tarefa ativa continuam exigindo revisao.

- Sem --limit-native-backup-10m, preserva toda configuracao de backup. Com essa opcao, envolve somente o backup nativo em um limite de 600 segundos; nao gera dump alternativo nem repete uma falha. Horario e comentarios de pausa sao preservados. Um wrapper antigo somente e substituido no agendamento se seu corpo exato estiver revisado.
- Reconhece um segundo corpo exato revisado de monitor legado, normalizando apenas as duas credenciais Telegram. Nenhuma credencial do servidor foi incorporada.
- Permite reparar um conjunto parcial SOMENTE quando cada arquivo presente tem hash/corpo revisado. Arquivos desconhecidos continuam recusados.
- Ignora copias arquivadas com ponto no nome em /etc/cron.d, assim como o cron Debian.
- Preserva correcoes de corrida na identidade do processo, escalonamento controlado do FreeRADIUS/MariaDB, diagnostico com timeout, detector sql/sqlippool/preacct/core/queue, mensagens detalhadas e coordenacao opcional do iniciador nativo.

## Limite do backup nativo

--limit-native-backup-10m instala uma unica chamada supervisionada de /opt/mk-auth/scripts/backup.php. Ao exceder 600 segundos, envia TERM apenas ao novo grupo de processos da tarefa, aguarda ate 5 segundos e usa KILL nesse grupo se necessario. Confirma a identidade do lider, preserva os artefatos e alerta. Nao mata diretamente MariaDB ou RADIUS; o monitor separado continua tratando indisponibilidade e locks. Se nao for possivel confirmar encerramento, bloqueia novas tentativas ate revisao local. Processos em espera ininterruptivel de kernel podem nao encerrar imediatamente.

Reserva de disco antes/durante a tarefa, limite de log de 1 MiB e arquivo de 1 GiB continuam protegendo o espaco. Nao apaga SQLs/.maz nem altera o codigo PHP nativo. Validacao estrutural nao certifica restauracao.

## Politica explicita

As opcoes --allow-sigkill-exact-mariadb e --allow-sigkill-exact-radius autorizam encerramento forcado como ultimo recurso depois de prazo/TERM, confirmacao de identidade e evidencia. Podem perder requisicoes em andamento; MariaDB/TokuDB pode exigir recuperacao de crash. Nao ha garantia de recuperacao em toda falha.

--cancel-redundant-radius-ddl autoriza cancelar somente ALTER de collation redundante ainda aguardando lock, apos conferir QUERY_ID e collation. --restart-database-on-persistent-queue inclui banco na recuperacao apos os criterios de persistencia. --coordinate-native-mariadb coordena os caminhos nativos revisados para evitar partidas concorrentes; recusa layouts desconhecidos. --upgrade-reviewed-sqlippool continua opcional e pode reiniciar apenas RADIUS para carregar o binario revisado.

O protector comenta apenas ALTERs redundantes em /opt/mk-auth/mysql/up_database.sql, preservando copia em /root/mkauth-guardian-safety-backups. O coordenador verifica a cada 30 segundos. As etapas de recuperacao tem limites e podem exigir intervencao humana; disco cheio, kernel preso, corrupcao e falhas fisicas nao se resolvem apenas com restart.

## Rollback

A instalacao grava manifesto/hashes/copia em /root/mkauth-normal-recovery-backups. O pacote extraido contem rollback.py: primeiro simule com o diretorio informado e --expected-provider; use --apply apenas apos revisar. Coordenacao nativa opcional tem copia separada indicada no log de instalacao. Rollback nao desfaz comentarios do protector automaticamente.

## Limites

Nao converte engines, nao repara tabelas nem ativa recuperacao destrutiva. Origem de toda lentidao, restauracao de cada .maz e falha historica de segmentacao nao estao certificadas. O backup nativo e supervisores antigos exigem auditoria separada.

## Migração de monitor legado com nome de provedor

Reconhece a variante revisada com nome literal do provedor no alerta, preservando token e chat sem executar o script. Instalação sem monitor continua usando o mesmo instalador. Alterações nos comandos, lógica ou expansões de shell não são aceitas. Não repara corrupção do banco.
