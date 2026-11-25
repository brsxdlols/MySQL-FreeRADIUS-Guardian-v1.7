"""Recognize FreeRADIUS queue warnings with bare and bracketed module names."""
import re

UNFINISHED=re.compile(rb'unfinished request in component[^\r\n]*\bmodule[ \t]+(?:<(?:queue|sql|sqlippool|preacct)>|(?:queue|sql|sqlippool|preacct)\b)',re.I)

def count_unfinished(data):
    return len(UNFINISHED.findall(data))

# Distinct from duplicate/unfinished messages: the server explicitly rejects new work.
FULL_QUEUE=re.compile(
    rb'^(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[ \t]+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[ \t]+[0-9]{1,2}[ \t]+[0-9]{2}:[0-9]{2}:[0-9]{2}[ \t]+[0-9]{4}[ \t]*:[ \t]*)?'
    rb'Error:[ \t]+Something is blocking the server\.[ \t]+There are [1-9][0-9]* packets in the queue,[ \t]+waiting to be processed\.[ \t]+Ignoring the new request\.[ \t]*\r?$',re.I|re.M)


def count_queue_full(data):
    return len(FULL_QUEUE.findall(data))
