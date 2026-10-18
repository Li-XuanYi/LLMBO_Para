"""Deadline supervision for one owned native worker; no thread cancellation."""
import multiprocessing
import time


def run_with_deadline(worker,args,*,deadline,on_solve_start):
    if time.monotonic()>=deadline:raise TimeoutError('native execution deadline exhausted before preparation')
    parent,child=multiprocessing.get_context('spawn').Pipe()
    process=multiprocessing.get_context('spawn').Process(target=worker,args=(*args,child),daemon=True)
    process.start();child.close()
    try:
        while True:
            remaining=deadline-time.monotonic()
            if remaining<=0:raise TimeoutError('native execution deadline exhausted')
            if parent.poll(min(remaining,.05)):
                try:kind,value=parent.recv()
                except EOFError:raise RuntimeError('native worker closed without a result') from None
                if kind=='solve_started':on_solve_start();parent.send('continue')
                elif kind=='result':return value
                elif kind=='error':raise RuntimeError('native worker '+value)
                else:raise RuntimeError('invalid native worker protocol')
            if not process.is_alive() and not parent.poll():raise RuntimeError('native worker exited without a result')
    finally:
        if process.is_alive():process.terminate()
        process.join(timeout=1);parent.close()
