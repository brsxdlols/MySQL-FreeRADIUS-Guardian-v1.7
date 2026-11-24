# Validação — 24/11/2026

Reconhecimento da variante legada com nome literal do provedor, preservação de credenciais, recusa de comandos alterados, expansões de shell e comandos extras, compatibilidade CRLF e migração sem executar o monitor antigo. O cenário sem monitor verifica explicitamente o perfil first_install.

A fonte privada coletada foi reconhecida localmente sem execução ou exposição das credenciais. A suíte completa exige Linux (fcntl e sinais) e deve ser conferida no Guardian Recovery Linux CI deste commit, que testa o pacote embarcado real em Python 3.7 sem rede.

Nenhuma instalação desta versão foi aplicada no R-NET. A recuperação do banco foi abortada a pedido do usuário; esta alteração de instalador não repara corrupção InnoDB nem certifica restauração de backups.
