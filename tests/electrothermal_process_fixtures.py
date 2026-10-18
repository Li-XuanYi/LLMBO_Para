"""Picklable, zero-DFN workers for native deadline supervision tests."""
import time


def stalled_worker(phase,connection):
    if phase=='solve':
        connection.send(('solve_started',None));connection.recv()
    while True:time.sleep(1)
