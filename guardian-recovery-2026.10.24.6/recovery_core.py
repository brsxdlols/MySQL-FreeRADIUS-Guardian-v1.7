"""Coordinated recovery; exact-PID escalation requires explicit authorization."""
import time

def begin(reason, database, now=None, allow_sigkill=False, allow_radius_sigkill=False):
    now = time.time() if now is None else now
    return {'phase':'stop_radius','reason':reason,'database':database,'started':now,'phase_at':now,'events':[], 'allow_sigkill':bool(allow_sigkill),'allow_radius_sigkill':bool(allow_radius_sigkill)}

def step(state, backend, now=None):
    now = time.time() if now is None else now
    phase = state['phase']
    def move(target):
        state['events'].append({'phase':phase,'next':target,'at':now})
        state['phase']=target;state['phase_at']=now
    if phase in ('done','manual'):
        return state
    command = state.get('command')
    waiting_database = phase in ('wait_database_stop','wait_database_term','wait_database_kill','database_TERM','database_KILL')
    if command and backend.command_running(command) and not waiting_database:
        if now-state['phase_at'] > 300:
            state['error']='service command still running; no overlapping command permitted'
            move('manual')
        return state
    if not waiting_database:state.pop('command',None)
    if phase == 'stop_radius':
        state['old_radius'] = backend.identity('radius')
        if state['old_radius']:
            try:backend.stop_radius(state['old_radius'],state)
            except Exception:
                if not backend.same_process(state.get('old_radius')):
                    move('wait_radius_stop');return state
                state['error']='Radius TERM refused or evidence could not be saved';state['error_code']='radius_signal_refused';move('manual');return state
        move('wait_radius_stop')
    elif phase == 'wait_radius_stop':
        if backend.same_process(state.get('old_radius')):
            if now-state['phase_at'] > 90:
                
                if state.get('allow_radius_sigkill'):move('radius_KILL')
                else:
                    state['error']='Radius did not exit after TERM; no SIGKILL permitted';state['error_code']='radius_exit_timeout';move('manual')
        else:
            move('stop_database' if state['database'] else 'start_radius')
    elif phase == 'radius_KILL':
        if not state.get('allow_radius_sigkill'):
            state['error']='Exact Radius escalation not authorized';state['error_code']='radius_signal_refused';move('manual')
        elif not backend.same_process(state.get('old_radius')):
            move('wait_radius_stop')
        elif state.get('radius_kill_reserved'):
            state['error']='Radius signal attempt already reserved; manual review required';state['error_code']='radius_signal_refused';move('manual')
        else:
            state['radius_kill_reserved']=True
            try:
                backend.signal_radius(state['old_radius'],'KILL',state)
                state['used_radius_sigkill']=True;state['used_sigkill']=True;move('wait_radius_kill')
            except Exception:
                if not backend.same_process(state.get('old_radius')):
                    move('wait_radius_kill');return state
                state['error']='Exact Radius signal refused or evidence could not be saved';state['error_code']='radius_signal_refused';move('manual')
    elif phase == 'wait_radius_kill':
        if not backend.same_process(state.get('old_radius')):
            move('stop_database' if state['database'] else 'start_radius')
        elif now-state['phase_at']>60:
            state['error']='Radius remains alive after exact SIGKILL; no duplicate start';state['error_code']='radius_exit_timeout';move('manual')
    elif phase == 'stop_database':
        state['old_database'] = backend.identity('database')
        if state['old_database']:
            state['command']=backend.shutdown_database()
        move('wait_database_stop')
    elif phase in ('wait_database_stop','wait_database_term','wait_database_kill'):
        if backend.same_process(state.get('old_database')):
            limit=240 if phase=='wait_database_stop' else 120 if phase=='wait_database_term' else 60
            if now-state['phase_at'] > limit:
                if not state.get('allow_sigkill') or phase=='wait_database_kill':
                    state['error']='Database did not exit; manual intervention required, no duplicate start';move('manual')
                else:
                    move('database_TERM' if phase=='wait_database_stop' else 'database_KILL')
        elif backend.identity('database'):
            # Another actor started a daemon. Never launch a duplicate instance.
            state.pop('command',None)
            move('wait_database_ready')
        else:
            state.pop('command',None)
            move('start_database')
    elif phase in ('database_TERM','database_KILL'):
        if not state.get('allow_sigkill'):
            state['error']='Exact-PID escalation not authorized';move('manual')
        elif not backend.same_process(state.get('old_database')):
            move('wait_database_stop')
        else:
            try:
                backend.signal_database(state['old_database'],phase.rsplit('_',1)[1],state)
                state['used_sigkill']=phase=='database_KILL' or state.get('used_sigkill',False)
                move('wait_database_term' if phase=='database_TERM' else 'wait_database_kill')
            except Exception:
                state['error']='Exact-PID signal refused or evidence could not be saved';move('manual')
    elif phase == 'start_database':
        if backend.database_ready():
            move('start_radius')
        elif backend.identity('database'):
            move('wait_database_ready')
        else:
            state['command']=backend.start('database');move('wait_database_ready')
    elif phase == 'wait_database_ready':
        if backend.database_ready():
            move('start_radius')
        elif now-state['phase_at'] > 240:
            state['error']='Database failed to become available';move('manual')
    elif phase == 'start_radius':
        if not backend.identity('radius'):
            state['command']=backend.start('radius')
        move('wait_radius_ready')
    elif phase == 'wait_radius_ready':
        if backend.database_ready() and backend.radius_ready():
            state['availability_only']=True
            move('done')
        elif now-state['phase_at'] > 90:
            state['error']='Radius failed availability check';move('manual')
    else:
        state['error']='Unknown recovery phase';move('manual')
    return state


def resume_radius_manual(state,backend,now=None,allow_radius_sigkill=False):
    """Only a known Radius exit timeout may resume; unrelated manual failures stay closed."""
    now=time.time() if now is None else now
    if state.get('phase')!='manual':return False
    known=state.get('error_code')=='radius_exit_timeout' or state.get('error')=='Radius did not exit after TERM; no SIGKILL permitted'
    if not known or not state.get('old_radius'):return False
    if not backend.database_ready():return False
    alive=backend.same_process(state['old_radius'])
    if alive:
        if not allow_radius_sigkill or state.get('radius_kill_reserved') or state.get('used_radius_sigkill'):return False
        target='radius_KILL'
    else:
        target='stop_database' if state.get('database') else 'start_radius'
    state['events'].append({'phase':'manual','next':target,'at':now,'reason':'authorized_radius_timeout_resume'})
    state.update(phase=target,phase_at=now,allow_radius_sigkill=bool(allow_radius_sigkill))
    state.pop('error',None);state.pop('error_code',None)
    return True
