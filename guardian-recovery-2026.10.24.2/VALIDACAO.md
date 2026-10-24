# Validação — 24/10/2026, versão 2026.10.24.2

122 testes automatizados passaram em Linux/Python 3.7 no Demo. Incluem o fluxo real do controlador com política de reinício dos dois serviços, aviso isolado sem reinício, retomada de término tardio, estado manual com saúde atualizada, sinal recusado quando a identidade muda ou evidência falha, limite de sinal, política explicitamente autorizada e diagnóstico SQL com prazo também no servidor.

Três cenários de integração reais em instâncias isoladas no Demo passaram: (1) transação mantendo metadata lock, ALTER redundante em espera e INSERT enfileirado; cancelamento pelo QUERY_ID liberou o INSERT; (2) FreeRADIUS isolado suspenso, SIGTERM sem saída e SIGKILL via pidfd no PID exato; o controlador encerrou o banco isolado e iniciou banco e RADIUS uma única vez nessa ordem; (3) sinal dirigido a processo já encerrado foi recusado. Os PIDs dos serviços ativos do Demo permaneceram iguais. Não foi travado nem reiniciado o GLOBAL para testar.

Na preparação do teste, duas execuções de laboratório pararam por detalhes do harness: cliente mysql de transação não encerrou com o comando de saída no mesmo buffer e o daemon RADIUS em foreground não gravava PID file. As rotinas preservaram os serviços ativos, encerraram as instâncias isoladas e os casos foram repetidos em diretórios novos com saída por EOF e confirmação do socket associado ao PID. A execução v3 concluiu todos os casos. Isso não equivale a ter simulado todo defeito de disco, kernel ou banco de produção.

A validação de backup e os testes anteriores abaixo são históricos. Esta versão não certifica novos backups de outro provedor e não implementa limpeza dos temporários acumulados.

## Histórico anterior

# Validação — 21/10/2026, versão 2026.10.24.2

Atualização: 93 testes automatizados Linux/Python 3.7. Incluem seleção de candidato anterior compatível sem ampliar caminhos, recusa de tabelas divergentes, preservação exata do cron nativo quando o backup requer homologação, manutenção de modelo já revisado, recusa de roteamento inesperado e aviso de backup pendente no terminal/Telegram. As validações de restauração abaixo referem-se à versão anterior do gerador, cujo código de geração e preservação de permissões permanece nesta atualização. Não equivalem a homologação do backup de outro provedor.

82 testes automatizados passaram em Linux/Python 3.7. Os novos casos verificam política ausente, referência de restauração obrigatória, provedor divergente, configuração exposta ou symlink, seleção do gerador compatível sem iniciar o nativo e propagação de falha de dump. Um modelo pequeno completo é aceito; um pequeno incompleto continua rejeitado. Os testes de metadados verificam UID/GID/modo/timestamp dos arquivos originais nos cabeçalhos e manutenção do modo 600 nas cópias temporárias.

Com o gerador corrigido, novo arquivo de 50.847 bytes foi produzido no Demo. Foram conferidos os 18 cabeçalhos contra os originais e os acessos de leitura/escrita sob UID/GID do serviço web. Os cinco SQLite acessíveis ao serviço passaram em quick_check. Arquivos originalmente inacessíveis ao serviço continuaram inacessíveis. Os dados foram preservados. O teste inicial de acesso usou caminho privado cujo diretório pai impedia a abertura SQLite; a conferência final foi executada em diretório temporário acessível ao grupo do serviço, depois novamente guardado em área privada. Não houve mudança de permissão nos metadados originais.

Integração no Demo: gerado arquivo compatível de 50.778 bytes, com 55 tabelas e 18 metadados. Sua restauração em instância isolada importou as 55 tabelas e passou nos 55 CHECK TABLE QUICK e nas verificações dos metadados. O banco de teste encerrou normalmente. Nesse teste, o preflight do protetor foi somente leitura para preservar o SQL nativo do Demo; a política e o dump foram exercitados de fato. Não houve alteração de cron nem reinício dos serviços do Demo. Esse novo arquivo não foi restaurado pelo painel.

A restauração pelo painel foi validada anteriormente com outro arquivo compatível do mesmo gerador. Nenhum desses ensaios certifica automaticamente todos os futuros arquivos ou versões de MK-AUTH. O instalador não ativa a nova política em outros provedores.

As seções abaixo preservam o histórico de testes anteriores e suas limitações naquele momento.

# Histórico — 20/10/2026

## Concluído

17 testes automatizados passaram no Linux com Python 3.7: ordem de parada e partida; recuperação só do RADIUS; banco que não encerra; RADIUS que ignora TERM; banco que não fica disponível; comando pendente; partida por outro ator; escalada autorizada TERM/KILL; processo que continua após KILL; falha na gravação de evidência; cliente de shutdown preso; identidade de PID alterada; preservação e marcação de backup inválido; nome de arquivo inseguro; dumps incompletos; cabeçalhos e rodapés independentes por tabela; tabela ausente.

Integração em instâncias separadas de MariaDB 10.3.27/TokuDB e FreeRADIUS 3.0.17:

- Bloqueio de metadados por DDL reproduzido; timeout do DDL de teste e retomada do accounting confirmados.
- Dump transacional de dados sintéticos e restauração sintética concluídos; dump de tabela inexistente falhou com retorno detectável.
- Accounting Start, Interim-Update e Stop retornaram respostas e alteraram a tabela sintética.
- Recuperação dos dois daemons pela mesma máquina de estados concluída; accounting voltou após a recuperação.
- Conexão SQL interrompida com accounting em andamento; recuperação posterior e nova resposta confirmadas. O driver não apresentou a falha de segmentação histórica nesse teste.
- Instância sem TCP recebeu SIGSTOP para simular falta de resposta; shutdown, TERM e KILL passaram pela mesma máquina de estados. O envio real de TERM/KILL usou pidfd e evidências duráveis. O banco reiniciou e preservou o registro confirmado; a transação não confirmada foi desfeita.

No servidor auditado, duas chamadas do PHP de backup retornaram zero sem criar `.maz`; a supervisão identificou a falha. O fallback gerou um novo arquivo de 28.649.039 bytes, com 55 dumps e metadados, e passou na validação estrutural. A aplicação do patch não reiniciou os serviços. A reaplicação não produziu alterações.

## Não certificado

A primeira restauração completa chegou à tabela de accounting, com 49 tabelas presentes, mas foi interrompida por duração excessiva no laboratório limitado a 64 MB de cache TokuDB. Isso não constitui aprovação de restauração completa nem comprova corrupção do arquivo. Uma tentativa com capacidade maior é necessária.

Ainda não foi certificada a restauração das 55 tabelas até o fim, a restauração pelo painel MK-AUTH ou a rotina inteira da madrugada em todos os ambientes. Não houve reinício controlado dos serviços de produção nesta etapa. Não foi reproduzida nem corrigida de forma específica a falha de segmentação histórica.

A origem exata da falha silenciosa dentro do PHP nativo continua indeterminada. A ligação temporal entre backup e DDL não comprova que o backup seja o único iniciador do bloqueio. A atualização protege contra comandos de collation redundantes e coordena a recuperação; não garante recuperação de qualquer falha de disco, kernel ou engine.

Este material é um candidato de implantação. Não trate o resultado dos testes selecionados como certificação de todas as falhas possíveis ou de todos os MK-AUTH.

## Interface automatica 2026.10.20.3

Sete testes adicionais da interface passaram: deteccao automatica do provedor e preservacao do nome local; recusa da identidade explicita incorreta; ausencia de mensagem de sucesso apos falha; simulacao sem aplicacao ou Telegram; falha de entrega distinta de sucesso; Telegram desabilitado distinto de sucesso; reaplicacao identificada como validacao. Esses testes nao ampliam a certificacao de restauracao do backup.

O instalador autocontido passou em bash -n e executou os 24 testes no Python 3.7/Linux. A interface aplicou a atualizacao no ambiente auditado, detectou automaticamente a identidade do banco, preservou o nome local e exibiu o diretorio de rollback e a saude dos servicos. A API do Telegram confirmou a entrega da mensagem de conclusao. Nenhum servico foi reiniciado durante a aplicacao. A confirmacao depende das credenciais locais e da disponibilidade da API; nao certifica entrega em todos os outros servidores.

## Configuracao interativa 2026.10.20.4

Treze testes adicionais cobrem Enter para preservar nome e Telegram sem download; mudanca de nome; troca de token oculto e chat; Enter nos campos individuais; primeira configuracao com padroes; modo sem perguntas; Telegram desabilitado; fonte indisponivel com entrada privada manual; recusa de SHA incorreto; leitura da fonte somente como dados; erro de token sem exposicao do valor; shell quoting e preservacao de opcoes; recusa de controle no nome. Quatro testes de origem cobrem instalacao nova sem scripts, recusa de instalacao parcial, recusa de script desconhecido e atualizacao de scripts revisados. Nenhum deles certifica restauracao completa do backup ou uma instalacao nova em todas as variantes de MK-AUTH.

A versao 2026.10.20.4 passou em bash -n e nos 41 testes em Linux/Python 3.7. Em um terminal SSH real no ambiente auditado, os dois prompts foram respondidos com Enter; nome e credenciais foram preservados, a aplicacao terminou com codigo zero e o Telegram confirmou a entrega. A rotina de obtencao de padroes foi executada separadamente e seus valores comparados em memoria com os locais, sem imprimir segredos; ambos coincidiram. A primeira instalacao completa em outro MK-AUTH ainda depende das verificacoes de layout e backup e nao foi certificada como universal.

## Nome do grupo 2026.10.20.5

Sete testes adicionais cobrem consulta getChat com titulo de grupo, recusa da API sem titulo inventado, erro de rede sem exposicao do token/URL, conversa pessoal distinta de grupo, limpeza de caracteres de controle, exibicao do titulo e aviso explicito quando a consulta falha. Esses testes nao alteram as limitacoes de backup e recuperacao ja documentadas.

A versao 2026.10.20.5 executou os 48 testes em Linux/Python 3.7 e concluiu a instalacao pelo terminal SSH real. A API getChat retornou o titulo do grupo configurado, que foi exibido antes da pergunta de preservacao. Os valores foram mantidos com Enter e a API de envio confirmou a mensagem final. Os servicos permaneceram disponiveis. O titulo e as credenciais reais nao foram incluidos nos testes ou no pacote publico.

## Incidente de accounting e detector 2026.10.24.2

Foi comprovado um falso negativo: mensagens reais em formato `component accounting module sql` estavam presentes enquanto o monitor contava zero, pois exigia angulos ao redor do modulo. O trecho privado capturado continha 37 avisos no formato simples, nenhum no formato reconhecido pelo filtro anterior. O cron e os servicos estavam ativos. Na primeira consulta os comandos SQL ja nao estavam bloqueados, portanto a causa inicial do bloqueio nao foi capturada nem atribuida ao backup.

Oito testes adicionais cobrem sql simples, queue com angulos, sqlippool, preacct, maiusculas/CRLF, repeticoes e recusa de mensagens/modulos diferentes. A nova captura privada e limitada permite observar os processos SQL antes da recuperacao em futuras ocorrencias. Nao se afirma que estes testes reproduzem todos os travamentos do ambiente.

A versao 2026.10.24.2 passou nos 56 testes e foi aplicada sem reiniciar os servicos. O arquivo real do incidente foi reprocessado privadamente: filtro anterior zero, filtro corrigido 37. Uma amostra somente de leitura de 30 sessoes ativas apresentou 20 alteracoes em 109 segundos, com atualizacao mais recente de dois segundos na segunda amostra. O accounting estava progredindo; isso nao certifica todas as sessoes nem comprova a causa inicial do atraso. Um novo lote curto foi registrado pelo monitor corrigido com quatro avisos, abaixo do limiar de recuperacao persistente.


## Atualizacao de 21/10/2026

70 testes passaram em Linux. Preflight do backup agora tenta adquirir o lock compartilhado por ate 180 segundos, sem remover locks, e alerta se esgotar o prazo. Testados sucesso imediato, ocupacao temporaria, prazo esgotado e excecao. Nao inclui modulo sqlippool candidato nem limpeza de cgroups. Restauracao completa do backup continua pendente.


## Atualizacao 2026.10.24.2 — migracao de monitor legado

Reconhece o corpo revisado do monitor antigo presente no QUALITY, inclusive quando e o unico script instalado. O reconhecimento usa SHA256 do corpo, substituindo somente duas atribuicoes literais de Telegram por marcadores. Nomes de variaveis, comandos, mensagens e demais linhas precisam corresponder ao perfil revisado; alteracoes de comportamento continuam recusadas. Nunca executar nem importar o shell antigo. A fixture incluida usa somente credenciais sinteticas.

Sem configuracao local, recupera token/chat das atribuicoes estaticas reconhecidas e usa o nome do provedor como nome inicial. Com configuracao existente, ela tem prioridade. O instalador interativo continua mostrando o nome do grupo consultado com getChat e permite manter/alterar os dados. O hash da fonte fica vinculado ao candidato para recusar mudancas entre a coleta e a aplicacao. Tokens nunca aparecem no plano ou no log.

Migra entradas simples de root em /etc/crontab e /etc/cron.d, comentando apenas chamadas conhecidas dos monitores. Preserva outros jobs. Aceita chamadas diretas, sh/bash, sleep de ate 59 segundos e flock -n com lock em /var/run, com redirecionamentos de log usuais. Comandos combinados com outras tarefas, agendamentos nao revisados e chamadas em crontab particular do root sao recusados para revisao; nao declarar compatibilidade universal com scripts desconhecidos.

Instalacao recusa monitor antigo ainda em execucao. Mudancas no cron sao aplicadas antes de trocar scripts, e o cron do coordenador e publicado por ultimo. A migracao com cron legado exige inicio entre os segundos 10 e 40 do minuto para evitar a borda habitual de disparo; fora dessa janela informa BUSY e pede nova tentativa, sem remover locks. Reconfere processos antigos durante a transacao e reverte arquivos se detectar concorrencia ou falha. Essa janela reduz a corrida com o cron, mas nao equivale a bloqueio atomico do daemon cron: uma rotina externa que ignore os mecanismos continua exigindo investigacao.

Nao reinicia MariaDB, FreeRADIUS, Docker ou cron durante a instalacao. Mantem a recuperacao da 2026.10.24.1 e as permissoes de encerramento forcado separadas, habilitadas somente pelas opcoes explicitas ou configuracao anterior. Recuperacao destrutiva permanece desabilitada.

Testes: 149 testes Linux aprovados, incluindo a execucao integral de install.main em filesystem redirecionado: migracao, segunda aplicacao sem escritas, falha apos alteracao do cron com rollback, processo legado ativo/concorrente, mudanca do hash durante o preparo e borda de horario. A preparacao real do QUALITY foi validada em memoria, somente leitura: perfil legacy_single_monitor, uma entrada em /etc/crontab e ambos os campos Telegram disponiveis. Nenhuma instalacao foi aplicada ao QUALITY nesta validacao.

Limites anteriores permanecem: este ajuste nao corrige por si so a segfault do modulo SQL, nao altera engines, nao certifica todo backup futuro e nao implementa retencao dos arquivos temporarios.
