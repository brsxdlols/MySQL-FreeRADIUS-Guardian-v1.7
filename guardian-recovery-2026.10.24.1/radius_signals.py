"""Recognize FreeRADIUS queue warnings with bare and bracketed module names."""
import re

UNFINISHED=re.compile(rb'unfinished request in component[^\r\n]*\bmodule[ \t]+(?:<(?:queue|sql|sqlippool|preacct)>|(?:queue|sql|sqlippool|preacct)\b)',re.I)

def count_unfinished(data):
    return len(UNFINISHED.findall(data))
