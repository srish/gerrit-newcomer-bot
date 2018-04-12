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

# Paramiko client
client = paramiko.SSHClient()
client.load_system_host_keys()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(**options)
client.get_transport().set_keepalive(60)

class PatchsetStream(threading.Thread):
    """Threaded job; listens for Gerrit events patchset-created only
     and puts them in a queue."""
    def run(self):
        while 1:
            try:
                cmd_patchset_created = 'gerrit stream-events -s patchset-created -s ref-updated'
                _, stdout, _ = client.exec_command(cmd_patchset_created)
                for line in stdout:
                    queue.put(json.loads(line))
            except:
                logging.exception('Gerrit error')
            finally:
                client.close()
            time.sleep(5)

class WatchSubmitters():
    def isFirstTimeContributor(self, submitter):
        try:
            cmd_query_open_patches_by_owner = 'gerrit query --format=JSON status:open owner:"' + submitter + '"'
            _, stdout, _ = client.exec_command(cmd_query_open_patches_by_owner)
            
            rowCount = 0
            line_with_stats = stdout.readlines()

            if line_with_stats:
                json_data = json.loads(line_with_stats[0])
                print json_data
                rowCount = json_data.get("rowCount", "")

            if rowCount == 0:
                return True

            return False
        except:
            logging.exception('Gerrit error')

if __name__ == '__main__':
    stream = PatchsetStream()
    stream.daemon = True
    stream.start()

    while 1:
        # TODO later > obtain submitter value from the event dict below 
        submitter = WatchSubmitters()
        print "Is Srishakatux a first time contributor ? " + str(submitter.isFirstTimeContributor("Srishakatux"))

        event = queue.get()
        print event  

    stream.join()