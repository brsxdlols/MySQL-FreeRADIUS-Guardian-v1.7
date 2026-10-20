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
