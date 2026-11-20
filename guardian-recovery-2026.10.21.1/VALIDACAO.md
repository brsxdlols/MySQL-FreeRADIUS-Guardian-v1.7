# Validação — 20/10/2026

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

## Incidente de accounting e detector 2026.10.21.1

Foi comprovado um falso negativo: mensagens reais em formato `component accounting module sql` estavam presentes enquanto o monitor contava zero, pois exigia angulos ao redor do modulo. O trecho privado capturado continha 37 avisos no formato simples, nenhum no formato reconhecido pelo filtro anterior. O cron e os servicos estavam ativos. Na primeira consulta os comandos SQL ja nao estavam bloqueados, portanto a causa inicial do bloqueio nao foi capturada nem atribuida ao backup.

Oito testes adicionais cobrem sql simples, queue com angulos, sqlippool, preacct, maiusculas/CRLF, repeticoes e recusa de mensagens/modulos diferentes. A nova captura privada e limitada permite observar os processos SQL antes da recuperacao em futuras ocorrencias. Nao se afirma que estes testes reproduzem todos os travamentos do ambiente.

A versao 2026.10.21.1 passou nos 56 testes e foi aplicada sem reiniciar os servicos. O arquivo real do incidente foi reprocessado privadamente: filtro anterior zero, filtro corrigido 37. Uma amostra somente de leitura de 30 sessoes ativas apresentou 20 alteracoes em 109 segundos, com atualizacao mais recente de dois segundos na segunda amostra. O accounting estava progredindo; isso nao certifica todas as sessoes nem comprova a causa inicial do atraso. Um novo lote curto foi registrado pelo monitor corrigido com quatro avisos, abaixo do limiar de recuperacao persistente.


## Atualizacao de 21/10/2026

70 testes passaram em Linux. Preflight do backup agora tenta adquirir o lock compartilhado por ate 180 segundos, sem remover locks, e alerta se esgotar o prazo. Testados sucesso imediato, ocupacao temporaria, prazo esgotado e excecao. Nao inclui modulo sqlippool candidato nem limpeza de cgroups. Restauracao completa do backup continua pendente.
