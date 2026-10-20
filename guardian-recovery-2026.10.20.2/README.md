# Guardian Recovery 2026.10.20.2 — candidato de implantação

Atualização para instalações existentes do Guardian MK-AUTH. Não é um instalador universal do MK-AUTH. Testado com MariaDB 10.3.27, TokuDB e FreeRADIUS 3.0.17 no ambiente auditado e em instâncias isoladas no mesmo servidor.

## O que muda

- Um coordenador e um lock de recuperação compartilhado substituem os três fluxos concorrentes. Preserva credenciais locais de Telegram e MariaDB; não inclui credenciais no pacote.
- Compara a collation atual antes de comentar somente comandos `ALTER TABLE ... COLLATE='latin1_swedish_ci'` redundantes no arquivo de atualização. Faz cópia privada e não executa DDL.
- Para o RADIUS antes do encerramento do banco. Solicita shutdown pelo mysqladmin, confirma a saída do processo antigo e só então inicia os serviços. Não usa `service mysql stop/restart`, `killall` ou `pkill`.
- Verifica falhas consecutivas, filas novas no log e bloqueios críticos. Limita recuperações concluídas a duas do banco por hora e quatro totais por hora, com intervalo mínimo de cinco minutos. Falha definitiva exige intervenção e bloqueia novas tentativas automáticas.
- O supervisor de backup recusa sucesso sem arquivo novo válido e preserva arquivos inválidos em quarentena. Quando o PHP nativo falha, tenta um dump único com `--single-transaction --quick --skip-lock-tables`, usando o layout aprendido de um `.maz` nativo estruturalmente válido. Não copia arquivos pessoais do servidor para este repositório.
- Desativa as rotinas antigas identificadas de limpeza agressiva e mantém inventário sem apagar backups por idade. Não reinicia Docker nem executa prune.

## Instalação

Requisitos: root, Linux x86_64, Python 3.7+, ferramentas MariaDB, flock, service, ss, estrutura padrão `/var/lib/mysql`, configuração local existente do Guardian, três scripts com hashes revisados e ao menos um `.maz` nativo estruturalmente válido. Outros layouts ou scripts modificados são recusados; não remova essas verificações para forçar a instalação.

Baixe o instalador na revisão publicada, confira o SHA-256 informado junto à publicação e faça primeiro a simulação. Substitua o nome pelo valor exato de `sis_provedor.nome` daquele servidor:

```sh
bash -n /root/instalador-guardian-recovery.sh
bash /root/instalador-guardian-recovery.sh --expected-provider 'NOME EXATO DO PROVEDOR' --enable-normal-recovery
```

Depois de revisar os caminhos exibidos:

```sh
bash /root/instalador-guardian-recovery.sh --expected-provider 'NOME EXATO DO PROVEDOR' --enable-normal-recovery --apply
```

A instalação não reinicia serviços. O modo habilitado poderá recuperá-los depois de uma falha confirmada. O comportamento deve ser validado em um servidor por vez antes de expandir.

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
