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

# Bot details
reviewerBot = "First-time-contributor"
welcomeMessage = "Thank you for making your first contribution to Wikimedia! :)"  \
    "To start contributing code to Wikimedia, " \
    "read https://www.mediawiki.org/wiki/New_Developers | " \
    "To get an overview of technical and non-technical contribution ideas, "\
    "read https://www.mediawiki.org/wiki/How_to_contribute | No answer? "\
    "Try https://discourse-mediawiki.wmflabs.org"


class WatchPatchsets(threading.Thread):
    """Threaded job; listens for Gerrit events patchset-created only
     and puts them in a queue."""

    def run(self):
        while True:
            try:
                cmd_patchset_created = 'gerrit stream-events -s patchset-created -s ref-updated'
                _, stdout, _ = client.exec_command(cmd_patchset_created)
                for line in stdout:
                    queue.put(json.loads(line))
            except BaseException:
                logging.exception('Gerrit error')
            finally:
                client.close()
            time.sleep(5)


class WatchNewContributors():
    def __init__(self):
        self.isNewContributor = False
        self.isFirstTimeContributor = False

    def identify(self, submitter):
        try:
            cmd_query_patches_by_owner = 'gerrit query --format=JSON owner:"' \
                + submitter + '"'
            _, stdout, _ = client.exec_command(cmd_query_patches_by_owner)

            rowCount = 0
            lines = stdout.readlines()
            numLines = len(lines)

            if numLines >= 1:
                json_data = json.loads(lines[numLines - 1])
                if json_data:
                    rowCount = json_data.get("rowCount")

            if rowCount == 1:
                self.isFirstTimeContributor = True
            elif rowCount > 0 and rowCount <= 5:
                self.isNewContributor = True
        except BaseException:
            logging.exception('Gerrit error')

    def getIsFirstTimeContributor(self):
        return self.isFirstTimeContributor

    def getIsNewContributor(self):
        return self.isNewContributor

    def addReviewer(self, project, changeID):
        try:
            cmd_set_reviewers = 'gerrit set-reviewers --project ' \
                + project + ' -a ' + reviewerBot + ' ' + changeID
            _, stdout, _ = client.exec_command(cmd_set_reviewers)

        except BaseException:
            logging.exception('Gerrit error')

    def getCurrentPatchset(self, submitter):
        try:
            cmd_query_cur_patch_set = 'gerrit query --format=JSON --current-patch-set owner:' \
                + submitter
            _, stdout, _ = client.exec_command(cmd_query_cur_patch_set)
            lines = stdout.readlines()

            if lines[0]:
                curPatch = json.loads(lines[0])
                return curPatch
            return

        except BaseException:
            logging.exception('Gerrit error')

    def addComment(self, curRev):
        try:
            cmd_review = 'gerrit review -m "' + welcomeMessage + '" ' + curRev
            client.exec_command(cmd_review)
        except BaseException:
            logging.exception('Gerrit error')


if __name__ == '__main__':
    stream = WatchPatchsets()
    stream.daemon = True
    stream.start()

    while True:
        submitter = WatchNewContributors()
        # TODO later > obtain submitter value from the event dict below
        submitter.identify("Srishakatux")
        firstTimeContrib = submitter.getIsFirstTimeContributor()

        if firstTimeContrib:
            curPatch = submitter.getCurrentPatchset("Srishakatux")

            project = curPatch.get("project")
            changeID = curPatch.get("id")
            curRev = curPatch.get("currentPatchSet").get("revision")

            submitter.addReviewer(project, changeID)
            submitter.addComment(curRev)

        newContrib = submitter.getIsNewContributor()

        if newContrib:
            print "I am a new contributor"

        event = queue.get()
        print event

    stream.join()
