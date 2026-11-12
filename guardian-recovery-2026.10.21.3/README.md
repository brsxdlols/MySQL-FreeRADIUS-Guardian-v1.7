# Guardian Recovery 2026.10.21.3 — candidato de implantação

Instalacao e atualizacao do Guardian em MK-AUTH com estrutura padrao. Nao instala o proprio MK-AUTH ou MariaDB. Testado com MariaDB 10.3.27, TokuDB e FreeRADIUS 3.0.17 no ambiente auditado e em instancias isoladas.

## O que muda

- Um coordenador e um lock de recuperação compartilhado substituem os três fluxos concorrentes. Preserva credenciais locais de Telegram e MariaDB; não inclui credenciais no pacote.
- Compara a collation atual antes de comentar somente comandos `ALTER TABLE ... COLLATE='latin1_swedish_ci'` redundantes no arquivo de atualização. Faz cópia privada e não executa DDL.
- Para o RADIUS antes do encerramento do banco. Solicita shutdown pelo mysqladmin, confirma a saída do processo antigo e só então inicia os serviços. Não usa `service mysql stop/restart`, `killall` ou `pkill`.
- Verifica falhas consecutivas, filas novas no log e bloqueios críticos. Limita recuperações concluídas a duas do banco por hora e quatro totais por hora, com intervalo mínimo de cinco minutos. Falha definitiva exige intervenção e bloqueia novas tentativas automáticas.
- O supervisor de backup recusa sucesso sem arquivo novo válido e preserva arquivos inválidos em quarentena. Quando o PHP nativo falha, tenta um dump único com `--single-transaction --quick --skip-lock-tables`, usando o layout aprendido de um `.maz` nativo estruturalmente válido. Não copia arquivos pessoais do servidor para este repositório.
- Desativa as rotinas antigas identificadas de limpeza agressiva e mantém inventário sem apagar backups por idade. Não reinicia Docker nem executa prune.

## Instalação

Requisitos: root, Linux x86_64, Python 3.7+, ferramentas MariaDB, flock, service, ss, credenciais locais de MariaDB, datadir `/var/lib/mysql`, scripts e cron de backup nativo e ao menos um `.maz` nativo estruturalmente valido. Instalacao nova do Guardian aceita os tres scripts ausentes. Atualizacao exige os tres presentes e com hashes revisados. Instalacao parcial, scripts desconhecidos ou outros layouts sao recusados antes de alterar os arquivos.

A interface interativa pergunta:

```text
Nome deste MK-AUTH/VM [NOME ENCONTRADO]:
Grupo encontrado: NOME OBTIDO DO TELEGRAM
Chat ID: ID DO CHAT
Token encontrado: ******** (somente os quatro caracteres finais)
Manter o token e o chat desse grupo? [S/n]:
```

Enter mantem o nome. Digitar outro nome altera somente o nome local da VM, sem alterar o cadastro do provedor no banco. Enter ou S mantem Telegram. N permite informar um token com digitacao oculta e outro chat; Enter em cada campo mantem seu valor atual. O token completo nunca e exibido. Telegram anteriormente desabilitado permanece assim por padrao e pode ser ativado por escolha explicita.

Quando nome, token e chat existem, sao reaproveitados da configuracao local. Na primeira instalacao ou quando faltam credenciais, os padroes do datacenter sao lidos em memoria de uma revisao fixa do instalador v1.7.1 ja publicada pelo proprietario, apos verificar SHA-256. Esse script antigo nunca e executado. Os valores foram comparados em memoria com os configurados no ambiente de referencia e coincidem. Nenhum token ou chat real esta embutido no pacote novo.

Se a fonte estiver indisponivel na instalacao interativa, e possivel informar os valores localmente. O arquivo final fica em `/etc/default/check_backup_freeradius`, modo 600; dados temporarios privados sao removidos ao sair. Antes da gravacao, o instalador verifica se a configuracao mudou durante as perguntas e recusa sobrescrever alteracao concorrente.

```sh
bash -n /root/instalador-guardian-recovery.sh
bash /root/instalador-guardian-recovery.sh
```

Somente simular, sem perguntas, sem alterar configuracao ou enviar Telegram:

```sh
bash /root/instalador-guardian-recovery.sh --dry-run
```

Execucao sem terminal: use `--non-interactive` para manter valores locais ou utilizar padroes verificados quando ausentes. Isso nao ativa o ultimo recurso SIGKILL em servidores novos; essa autorizacao continua sendo uma opcao separada.

Ao concluir, exibe arquivos atualizados, rollback, politica de recuperacao, saude dos servicos e resultado real do Telegram. Falha ou recusa nao envia confirmacao de sucesso. Sem credenciais validas ou conectividade, a entrega pode falhar e isso e informado no terminal. Nao reinicia MariaDB, FreeRADIUS, Docker ou cron durante a instalacao.

Os padroes sao uma referencia fixa da publicacao antiga, nao uma consulta remota continua ao servidor de referencia. Tokens ja publicados devem ser substituidos; apos rotacao, escolha N para informar os novos dados privados. O pacote novo nao publica tokens adicionais nem contem credenciais SSH.


## Último recurso com SIGKILL: adesão explícita

Por padrão, a atualização não habilita SIGKILL em um servidor novo. Para autorizar especificamente o último recurso, acrescente `--allow-sigkill-exact-mariadb` tanto à simulação quanto à aplicação. A autorização fica persistida na configuração local. Remover a opção de uma execução futura não revoga uma autorização já persistida.

Sequência: shutdown e espera de 240 segundos; TERM no MariaDB confirmado e espera de 120 segundos; KILL no mesmo processo e espera de 60 segundos pela saída. A execução pelo cron acrescenta latência entre verificações. Não é um prazo rígido de recuperação total. A partida aguarda disponibilidade por até 240 segundos; se não ocorrer, para e alerta, sem repetir reinícios durante a recuperação do engine.

Sinais utilizam pidfd do kernel, validam PID, início do processo, executável e datadir, e gravam uma reserva durável por incidente e sinal antes do envio. Não repetem o sinal reservado após falha do controlador. Kernel sem suporte a pidfd, evidência indisponível ou processo diferente fazem a escalada parar. Um processo em espera de I/O não interrompível pode continuar após KILL: nesse caso não se inicia outra instância.

SIGKILL interrompe o encerramento limpo e pode exigir recuperação do TokuDB, tornar tabelas indisponíveis ou exigir restauração. O pacote não remove logs, arquivos do engine, sockets ou PID files e não ativa recuperação destrutiva. A flag antiga de recuperação destrutiva permanece desativada.

## Evidências e limites

Consulte `VALIDACAO.md` para os testes efetivamente concluídos. Testes isolados não garantem todos os defeitos possíveis, cargas, discos ou versões do MK-AUTH. A falha histórica de segmentação do driver não foi reproduzida e não é declarada corrigida.

O arquivo `.maz` deve conter SQL e metadados válidos; o tamanho sozinho não certifica um backup. Restauração SQL isolada não certifica a restauração pelo painel nativo. A transação única não garante consistência transacional de tabelas em engines não transacionais, nem atomicidade conjunta com os arquivos SQLite e de configuração. A seleção de tabelas acompanha o modelo nativo, não todos os bancos e addons do servidor.

O backup nativo que termina sem artefato foi comprovado; a causa interna do PHP permanece indeterminada. O fallback contorna a falha de geração. Jobs nativos que não encerram geram alerta após 15 minutos e bloqueiam sobreposição; não são encerrados à força. Não há promessa de que todo travamento seja automaticamente recuperável.

## Logs e rollback

Configuração: `/etc/default/mkauth-guardian-normal-recovery.json`. Estado: `/var/lib/mkauth-guardian-recovery/state.json`. Log: `/var/log/mkauth-guardian-normal-recovery.log`. Evidências de sinais: `/root/mkauth-normal-recovery-incidents`. Não publique esses arquivos sem sanitização.

A instalação informa um diretório privado em `/root/mkauth-normal-recovery-backups`. Para reverter arquivos, use o `rollback.py` distribuído, primeiro sem `--apply`:

```sh
python3 /root/DIRETORIO_EXTRAIDO/rollback.py /root/mkauth-normal-recovery-backups/ID --expected-provider 'NOME EXATO DO PROVEDOR'
```

Acrescente `--apply` após revisar. O rollback recusa arquivos alterados depois da instalação e recuperação ativa. Ele restaura configurações e crons anteriores, inclusive seus comportamentos antigos; não reverte automaticamente comentários do protector nem a quarentena. As cópias do SQL anterior ficam em `/root/mkauth-guardian-safety-backups`; a reversão deve comparar versões para não sobrescrever atualizações posteriores do fornecedor.

Tokens que já tenham sido publicados por versões antigas precisam ser revogados e substituídos pelo administrador; não estão incorporados nesta atualização.

O nome do destino e consultado pelo metodo getChat da API oficial do Telegram, antes da confirmacao. Grupos, canais e conversas pessoais sao identificados separadamente. Falha de rede, token invalido ou falta de acesso deixam o nome como nao confirmado; o instalador nao inventa um titulo. Se o operador alterar token/chat, consulta novamente o destino selecionado. A consulta nao envia mensagem ao grupo e nao ocorre na simulacao ou modo sem perguntas.

## Correcao do detector de accounting

O detector anterior reconhecia somente `module <sql>` e perdia os avisos reais `module sql`. A versao 2026.10.21.3 reconhece os dois formatos para sql, sqlippool, queue e preacct. Nao altera os limites de confirmacao ou a politica de sinais. Sintomas persistentes podem acionar recuperacao; a correcao do filtro nao prova a causa do bloqueio SQL.

Na primeira amostra com avisos, salva evidencia privada, no maximo uma vez a cada cinco minutos, em `/root/mkauth-guardian-queue-incidents`, com permissoes 700/600. A captura limitada contem log, memoria e processos SQL e pode incluir dados de clientes; nao publique seu conteudo. Esses dados sao somente lidos, sem ativar logs globais ou reiniciar servicos.


Telegram: detailed installation and incident notifications; local identity, timestamps, duration, initial evidence, escalation and availability. No raw SQL or customer logs are sent. Availability checks do not certify functional accounting. Recovery limits and locks remain unchanged.
# Atualização 2026.10.21.3 — permissões dos metadados e política de backup

Corrige um defeito do gerador compatível: os cabeçalhos do tar agora usam modo, UID, GID e timestamp dos arquivos originais. As cópias temporárias continuam privadas, com modo 600. A versão anterior gravava os modos e proprietários das cópias privadas, o que podia impedir acesso após restauração. Essa limitação afeta os backups compatíveis anteriores a esta correção, mesmo quando o conteúdo SQL é íntegro. Não afirmar restauração integral do painel apenas com importação SQL e hashes dos metadados.

Sem configuração adicional, permanece o fluxo `native_first`: tentativa nativa e contingência compatível se houver falha. O instalador não ativa automaticamente o caminho principal compatível em outros provedores.

O supervisor reconhece `/etc/default/mkauth-guardian-backup-policy.json`, arquivo regular de root, sem acesso de grupo/outros. Modo `compatible_primary` exige `validated_provider` igual ao nome consultado no banco local e `restore_reference_sha256` com a referência de homologação. A presença da referência é uma declaração do operador; o software não afirma ter restaurado cada novo arquivo.

O caminho principal compatível mantém lock contra sobreposição, preflight, conferência de bloqueios e validação antes de publicação. Ele usa o gerador de dump único já existente e não executa o PHP nativo. Não adiciona reinício de serviço nem alteração de engine.

Modelos de backup pequenos agora passam pelos mesmos validadores de conteúdo: arquivos menores que 100 KB não são descartados apenas pelo tamanho. Dumps incompletos continuam rejeitados.

Rollback da política: gravar atomicamente `{"mode":"native_first"}` no arquivo privado. Se houver execução em andamento, aguardar seu encerramento; não remover locks nem iniciar um segundo backup. O rollback do código usa o snapshot privado criado pelo instalador.

Esta versão não inclui a correção binária do sqlippool e não corrige o código interno do gerador nativo MK-AUTH. O caminho compatível é uma mitigação operacional explícita.

