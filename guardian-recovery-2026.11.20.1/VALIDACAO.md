# Validacao — 20/11/2026

31 testes independentes de reconhecimento de logs e interface/repeticao passaram no Windows local. A suite Linux completa e executada pelo fluxo Guardian Recovery Linux CI, usando Python 3.7 em conteiner e o pacote embarcado real, sem rede dentro do conteiner. Consulte o resultado dos checks do commit para a conclusao dessa suite.

Novos cenarios: mensagem real de 65536 pacotes, outras capacidades positivas, linhas incompletas recusadas, aviso dentro de autenticacao recusado, log antigo ignorado, amostras novas consecutivas, reset apos amostra limpa, cooldown, monitor desabilitado, permissoes de recuperacao do banco preservadas e repeticao limitada para BUSY. Os testes anteriores de recuperacao, sinais, migracao, rollback, backup nativo e Telegram permanecem.

O acesso SSH ao NEWLINK foi bloqueado pelo ambiente local nesta sessao (WinError 10013 antes de autenticacao). Nao houve coleta ou instalacao de producao durante a preparacao deste pacote. Nao ha certificacao de restauracao completa do backup ou recuperacao universal.
