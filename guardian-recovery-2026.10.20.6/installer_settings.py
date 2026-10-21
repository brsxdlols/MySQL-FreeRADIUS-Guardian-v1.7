"""Private local setup; never execute a downloaded installer or print credentials."""
import getpass
import hashlib
import json
import re
import shlex
import urllib.request
import urllib.parse

LEGACY_URL='https://raw.githubusercontent.com/brsxdlols/MySQL-FreeRADIUS-Guardian-v1.7/6edbb0e779ee2f5f7bd20999faf3a4958e3d5d51/instalador-completo-mkauth-v1.7.1-datacenter.sh'
LEGACY_SHA256='df93dce993122ab15043ba78e3f9ce1dec07cbf7ba5e136e10aa862b89df0c2e'
KEYS=('MKAUTH_NAME','USAR_TELEGRAM','TELEGRAM_BOT','TELEGRAM_CHAT_ID')
ASSIGN=re.compile(r'^\s*(?:export\s+)?([A-Z_]+)=(.*)$')

def parse_settings(text):
    values={}
    for row in text.splitlines():
        match=ASSIGN.match(row)
        if match and match[1] in KEYS:
            parts=shlex.split(match[2],comments=True)
            if len(parts)>1:raise RuntimeError('Configuracao local possui atribuicao nao suportada')
            values[match[1]]=parts[0] if parts else ''
    return values

def validate(values):
    name=values.get('MKAUTH_NAME','')
    if not name or len(name)>128 or re.search(r'[\x00-\x1f\x7f]',name):raise RuntimeError('Nome do MK-AUTH invalido')
    if values.get('USAR_TELEGRAM') not in ('sim','nao'):raise RuntimeError('Opcao Telegram invalida')
    if values['USAR_TELEGRAM']=='sim':
        if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]{20,}',values.get('TELEGRAM_BOT','')):raise RuntimeError('Formato do token Telegram invalido; valor omitido')
        if not re.fullmatch(r'(?:-?[0-9]{1,20}|@[A-Za-z0-9_]{5,64})',values.get('TELEGRAM_CHAT_ID','')):raise RuntimeError('Formato do chat Telegram invalido; valor omitido')

def defaults_from_source(data):
    if hashlib.sha256(data).hexdigest()!=LEGACY_SHA256:raise RuntimeError('Fonte do datacenter mudou; credenciais automaticas recusadas')
    text=data.decode('utf-8');values={}
    for key in ('TELEGRAM_BOT','TELEGRAM_CHAT_ID'):
        match=re.search(r'^'+key+r'=(.*)$',text,re.M)
        if not match:raise RuntimeError('Fonte do datacenter sem os campos esperados')
        parts=shlex.split(match[1],comments=True)
        if len(parts)!=1:raise RuntimeError('Fonte do datacenter possui formato nao suportado')
        values[key]=parts[0]
    validate(dict(values,MKAUTH_NAME='datacenter',USAR_TELEGRAM='sim'))
    return values

def fetch_defaults():
    # Immutable, hash-checked source already published by the owner. Read as data.
    # The token remains in memory until a root-only local config is installed.
    try:
        with urllib.request.urlopen(LEGACY_URL,timeout=15) as response:data=response.read(1048577)
    except Exception:raise RuntimeError('Nao foi possivel obter os padroes do datacenter; nenhuma credencial alterada') from None
    if len(data)>1048576:raise RuntimeError('Fonte do datacenter maior que o limite')
    return defaults_from_source(data)

def render_settings(original,values):
    validate(values);rows=[]
    for row in original.splitlines(keepends=True):
        match=ASSIGN.match(row.rstrip('\r\n'))
        if not match or match[1] not in KEYS:rows.append(row)
    text=''.join(rows)
    if text and not text.endswith('\n'):text+='\n'
    return text+''.join(key+'='+shlex.quote(values.get(key,''))+'\n' for key in KEYS)

def lookup_chat(token,chat):
    """Read Telegram getChat metadata only; never log URLs or API error bodies."""
    try:
        body=urllib.parse.urlencode({'chat_id':chat}).encode()
        with urllib.request.urlopen('https://api.telegram.org/bot'+token+'/getChat',data=body,timeout=8) as response:data=response.read(65537)
        if len(data)>65536:return {'status':'unavailable'}
        reply=json.loads(data)
        if reply.get('ok') is not True or not isinstance(reply.get('result'),dict):return {'status':'unavailable'}
        info=reply['result'];kind=info.get('type')
        if kind not in ('group','supergroup','channel','private'):return {'status':'unavailable'}
        title=info.get('title')
        if kind=='private':title=' '.join(str(info.get(k) or '') for k in ('first_name','last_name')).strip() or info.get('username')
        if not isinstance(title,str):return {'status':'unavailable'}
        title=re.sub(r'[\x00-\x1f\x7f]',' ',title).strip()[:200]
        if not title:return {'status':'unavailable'}
        return {'status':'ok','title':title,'type':kind}
    except Exception:return {'status':'unavailable'}

def show_chat(values,resolver):
    print('Consultando nome do destino no Telegram...',flush=True)
    info=resolver(values['TELEGRAM_BOT'],values['TELEGRAM_CHAT_ID'])
    if info.get('status')=='ok':
        label='Conversa encontrada' if info.get('type')=='private' else 'Canal encontrado' if info.get('type')=='channel' else 'Grupo encontrado'
        print(label+': '+info['title'],flush=True)
    else:print('Nome do grupo: nao confirmado; confira acesso do bot e conectividade.',flush=True)
    print('Chat ID: '+values['TELEGRAM_CHAT_ID'],flush=True)

def choose_settings(original,provider,interactive=True,read=None,secret=None,loader=None,resolver=None):
    read=input if read is None else read
    secret=getpass.getpass if secret is None else secret
    loader=fetch_defaults if loader is None else loader
    resolver=lookup_chat if resolver is None else resolver
    values=parse_settings(original);values.setdefault('MKAUTH_NAME',provider);values.setdefault('USAR_TELEGRAM','sim')
    if not values['MKAUTH_NAME']:values['MKAUTH_NAME']=provider
    if interactive:
        answer=read('Nome deste MK-AUTH/VM ['+values['MKAUTH_NAME']+']: ').strip()
        if answer:values['MKAUTH_NAME']=answer
    if values['USAR_TELEGRAM']=='nao':
        if not interactive or read('Manter Telegram desabilitado? [S/n]: ').strip().lower() not in ('n','nao','não'):
            validate(values);return values
        values['USAR_TELEGRAM']='sim'
    missing=[key for key in ('TELEGRAM_BOT','TELEGRAM_CHAT_ID') if not values.get(key)]
    if missing:
        try:defaults=loader()
        except RuntimeError:
            if not interactive:raise
            print('Padroes automaticos indisponiveis. Informe os dados localmente; token nao sera exibido.',flush=True)
            defaults={'TELEGRAM_BOT':secret('Token Telegram: ').strip(),'TELEGRAM_CHAT_ID':read('Chat ID: ').strip()}
        for key in missing:values[key]=defaults[key]
    validate(values)
    if interactive:
        show_chat(values,resolver)
        print('Token encontrado: ********'+values['TELEGRAM_BOT'][-4:],flush=True)
        answer=read('Manter o token e o chat desse grupo? [S/n]: ').strip().lower()
        if answer in ('n','nao','não'):
            token=secret('Novo token Telegram (Enter mantem o atual): ').strip()
            chat=read('Novo Chat ID ['+values['TELEGRAM_CHAT_ID']+']: ').strip()
            if token:values['TELEGRAM_BOT']=token
            if chat:values['TELEGRAM_CHAT_ID']=chat
            validate(values)
            show_chat(values,resolver)
        elif answer not in ('','s','sim','y','yes'):raise RuntimeError('Resposta invalida; nenhuma configuracao aplicada')
    validate(values)
    return values
