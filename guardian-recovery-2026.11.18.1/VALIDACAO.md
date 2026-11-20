# Validacao — 18/11/2026

187 testes aprovados em Linux/Python 3.7 usando o pacote embarcado. Incluem migracao transacional, rollback, idempotencia, preservacao de backups sem a opcao explicita, horario/comentarios de pausa preservados com limite nativo, recusa de wrappers desconhecidos ou comandos compostos, erro 255 sem dump alternativo, arquivos/logs limitados, falta de espaco e encerramento real de processos sinteticos que ignoram TERM. Os testes de prazo usam tempos reduzidos; nao foi provocado travamento de banco em producao.

A instalacao do Guardian anterior foi testada realmente no Demo, com backups e PIDs preservados. Instalacao real deste pacote no Demo, com limite habilitado, concluida; segunda simulacao sem alteracoes. Codigo PHP nativo e PIDs MariaDB/FreeRADIUS permaneceram iguais, e a condicao ativa/pausada do cron foi preservada. Os testes transacionais conferem o limite de 600 segundos sem segundo dump. Restauracao completa do .maz e recuperacao de toda falha nao certificadas.

Regressao da referencia historica comentada validada com cinco cenarios adicionais: rota ativa nativa e wrapper, duas ativas recusadas, varias pausadas recusadas e wrapper arquivado nao acessado pelo planejador.

Perfis adicionais revisados a partir de copias privadas dos monitores v1.4/v1.6 e seus agendamentos. Somente hashes foram adicionados ao pacote publico; nenhuma credencial ou codigo privado foi copiado. Criterios de sinais, cancelamento de DDL e prazo de backup mantidos.
