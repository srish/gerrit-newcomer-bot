#!/usr/bin/env python
"""
    watch_patchsets.py
    
    Watch events that get triggered when a patchset is created!

    :author: ***
"""

import ConfigParser
import Queue
import json
import logging
import threading
import time

import paramiko


queue = Queue.Queue()

# Logging

logging.basicConfig(level=logging.INFO)
logger = paramiko.util.logging.getLogger()
logger.setLevel(logging.INFO)

# Config

config = ConfigParser.ConfigParser()
config.read('gerrit.conf')

options = dict(timeout=60)
options.update(config.items('Gerrit'))
options['port'] = int(options['port'])


class PatchsetStream(threading.Thread):
    """Threaded job; listens for Gerrit events patchset-created only
     and puts them in a queue."""

    def run(self):
        while 1:
            client = paramiko.SSHClient()
            client.load_system_host_keys()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            try:
                client.connect(**options)
                client.get_transport().set_keepalive(60)
                _, stdout, _ = client.exec_command('gerrit stream-events -s patchset-created -s ref-updated')
                for line in stdout:
                    queue.put(json.loads(line))
            except:
                logging.exception('Gerrit error')
            finally:
                client.close()
            time.sleep(5)

gerrit = PatchsetStream()
gerrit.daemon = True
gerrit.start()

while 1:
    event = queue.get()
    # json output, ...
    print event

gerrit.join()
