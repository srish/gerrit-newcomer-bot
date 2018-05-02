#!/usr/bin/python3

"""
    watch_newcomers.py
    Welcomes newcomers and adds them to a group!
    MIT license
    :author: Srishti Sethi <ssethi@wikimedia.org>
"""

import os
import configparser
import queue
import json
import logging
import threading
import time
import paramiko
from requests.auth import HTTPBasicAuth
from pygerrit2.rest import GerritRestAPI

QUEUE = queue.Queue()

# Logging
logging.basicConfig(level=logging.INFO)
LOGGER = paramiko.util.logging.getLogger()
LOGGER.setLevel(logging.INFO)

# Load configuration
CONFIG = configparser.ConfigParser()

DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(DIR, 'gerrit.conf')

CONFIG.read(CONFIG_PATH)

GERRIT_SSH = dict()
GERRIT_SSH.update(CONFIG.items('Gerrit SSH'))
GERRIT_SSH['port'] = int(GERRIT_SSH['port'])
GERRIT_SSH['timeout'] = int(GERRIT_SSH['timeout'])

MISC = dict()
MISC.update(CONFIG.items('Misc'))

# Paramiko client
SSH_CLIENT = paramiko.SSHClient()
SSH_CLIENT.load_system_host_keys()
SSH_CLIENT.set_missing_host_key_policy(paramiko.AutoAddPolicy())
SSH_CLIENT.connect(**GERRIT_SSH)

# Rest client
REST_AUTH = HTTPBasicAuth(MISC['auth_username'], MISC['auth_password'])
REST_CLIENT = GerritRestAPI(url=MISC['base_url'], auth=REST_AUTH)

class WatchPatchsets(threading.Thread):
    """This class watches gerrit stream event patchset-created
    """
    def run(self):
        while True:
            try:
                cmd_patchset_created = 'gerrit stream-events -s patchset-created'
                _, stdout, _ = SSH_CLIENT.exec_command(cmd_patchset_created)
                for line in stdout:
                    QUEUE.put(json.loads(line))
            except BaseException:
                logging.exception('Gerrit error')
            finally:
                SSH_CLIENT.close()
            time.sleep(5)


class WelcomeNewcomersAndGroupThem():
    """This class check for number of patches of the submitter and
    categorizes them as:
    * First time contributor - if 1 patch in Gerrit
    * New contributor - more than 1 patch in Gerrit
    * Rising contributor - more than 5 patches in Gerrit
    It then adds a reviewer "First-time-contributor" and welcome message
    to a patch if the submitter is a first time contributor
    It also adds all first time and new contributors to a group 'Newcomer'
    """
    def __init__(self):
        self.new_contibutor = False
        self.first_time_contributor = False
        self.rising_contributor = False

    def identify(self, submitter):
        """ Identifies if a submitter is a first time, new or rising contributor
        """
        try:
            patches_by_owner = REST_CLIENT.get("/changes/?q=owner:" + submitter)
            num_patches = len(patches_by_owner)

            if num_patches == 1:
                self.first_time_contributor = True
            elif num_patches > 0 and num_patches <= 5:
                self.new_contibutor = True
            elif num_patches > 5:
                self.rising_contributor = True
        except BaseException:
            logging.exception('Gerrit error')

    def is_first_time_contributor(self):
        """ Returns first_time_contributor as boolean
        """
        return self.first_time_contributor

    def is_new_contibutor(self):
        """ Returns new_contributor as boolean
        """
        return self.new_contibutor

    def is_rising_contributor(self):
        """ Returns rising_contributor as boolean
        """
        return self.rising_contributor

    def add_reviewer_and_comment(self, change_id, cur_rev):
        """ Adds a reviewer "First-time-contributor" and welcome message
        to a patch
        """
        try:
            query = "/changes/" + str(change_id) + "/revisions/" + str(cur_rev) + "/review"
            REST_CLIENT.post(query, json={
                "message": MISC['welcome_message']
            })
        except BaseException:
            logging.exception('Gerrit error')

    def add_to_group(self, username):
        """ Adds newcomer to a group
        """
        try:
            query_add_member = "/groups/" + MISC['newcomer_group'] + \
                "/members/" + username
            REST_CLIENT.put(query_add_member)
        except BaseException:
            logging.exception('Gerrit error')

    def remove_from_group(self, username):
        """ Removes newcomer from a group
        """
        try:
            query_del_member = "/groups/" + MISC['newcomer_group'] + \
                "/members/" + username
            REST_CLIENT.delete(query_del_member)
        except BaseException:
            logging.exception('Gerrit error')


def main(event):
    """ Invokes functions of class 'WelcomeNewcomersAndGroupThem'
    """
    username = event['change']['owner']['username']
    change_id = event['change']['id']
    revision = event['patchSet']['revision']

    newcomer = WelcomeNewcomersAndGroupThem()
    newcomer.identify(username)

    if newcomer.is_first_time_contributor():
        newcomer.add_reviewer_and_comment(change_id, revision)
        newcomer.add_to_group(username)

    if newcomer.is_new_contibutor():
        newcomer.add_to_group(username)

    if newcomer.is_rising_contributor():
        newcomer.remove_from_group(username)

if __name__ == '__main__':
    STREAM = WatchPatchsets()
    STREAM.daemon = True
    STREAM.start()
    while True:
        EVENT = QUEUE.get()
        if EVENT:
            main(EVENT)

    STREAM.join()