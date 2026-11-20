"""Cancel only old, waiting, redundant collation DDL for allowlisted RADIUS tables."""
import re
TABLES=('radacct','radippool','radpostauth','radcheck','radreply','radusergroup','radgroupcheck','radgroupreply')
DDL=re.compile(r"^ALTER\s+TABLE\s+(?:`?mkradius`?\.)?`?("+'|'.join(TABLES)+r")`?\s+COLLATE\s*=\s*'([a-zA-Z0-9_]+)'\s*;?\s*$",re.I)
LOCK_QUERY="SELECT COUNT(*) FROM information_schema.PROCESSLIST WHERE ID<>CONNECTION_ID() AND TIME>=60 AND STATE LIKE '%lock%' AND ("+' OR '.join("INFO LIKE '%"+t+"%'" for t in TABLES)+");"
def parse_rows(text):
    rows=[]
    for line in text.splitlines():
        fields=line.split('\t',5)
        if len(fields)!=6:continue
        try:pid,seconds,qid=int(fields[0]),int(fields[2]),int(fields[4])
        except ValueError:continue
        rows.append({'id':pid,'schema':fields[1],'seconds':seconds,'state':fields[3],'query_id':qid,'query':fields[5]})
    return rows

def cancel_redundant(sql,evidence,min_seconds=60):
    raw=sql("SELECT ID,DB,TIME,STATE,QUERY_ID,INFO FROM information_schema.PROCESSLIST WHERE ID<>CONNECTION_ID() AND TIME>="+str(int(min_seconds))+" AND STATE='Waiting for table metadata lock' AND INFO LIKE 'ALTER TABLE%';")
    for row in parse_rows(raw):
        match=DDL.fullmatch(row['query'])
        if not match or row['schema']!='mkradius' or row['query_id']<1 or row['seconds']<min_seconds or row['state']!='Waiting for table metadata lock':continue
        table,collation=match[1].lower(),match[2].lower()
        actual=sql("SELECT TABLE_COLLATION FROM information_schema.TABLES WHERE TABLE_SCHEMA='mkradius' AND TABLE_NAME='"+table+"';").strip().lower()
        if actual!=collation:continue
        fresh=parse_rows(sql('SELECT ID,DB,TIME,STATE,QUERY_ID,INFO FROM information_schema.PROCESSLIST WHERE ID='+str(row['id'])+';'))
        if len(fresh)!=1 or any(fresh[0][key]!=row[key] for key in ['id','schema','state','query_id','query']) or fresh[0]['seconds']<min_seconds:continue
        record={'connection_id':row['id'],'query_id':row['query_id'],'table':table,'query':row['query'],'existing_collation':actual,'wait_seconds':fresh[0]['seconds'],'action':'cancel_waiting_redundant_ddl_only'}
        evidence(record) # Failure to save prevents any KILL.
        sql('KILL QUERY ID '+str(row['query_id'])+';')
        return record # At most one cancellation per sample.
    return None
