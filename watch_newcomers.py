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
import re
import paramiko
import requests
from requests.auth import HTTPBasicAuth
from pygerrit2.rest import GerritRestAPI
from twilio.rest import TwilioRestClient

QUEUE = queue.Queue()

# Logging
logging.basicConfig(level=logging.DEBUG,
                    filename='gerrit-newcomer-bot.log',
                    filemode='a+',
                    format='%(asctime)-15s %(levelname)-8s %(message)s')

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

TWILIO = dict()
TWILIO.update(CONFIG.items('Twilio'))

# Paramiko client
SSH_CLIENT = paramiko.SSHClient()
HOSTKEY_PATH = os.path.join(DIR, 'ssh-host-key')
SSH_CLIENT.load_host_keys(HOSTKEY_PATH)
SSH_CLIENT.set_missing_host_key_policy(paramiko.AutoAddPolicy())
SSH_CLIENT.connect(**GERRIT_SSH)

# Rest client
REST_AUTH = HTTPBasicAuth(MISC['auth_username'], MISC['auth_password'])
REST_CLIENT = GerritRestAPI(url=MISC['base_url'], auth=REST_AUTH)

# Twilio client
TWILIO_CLIENT = TwilioRestClient(TWILIO['account_sid'], TWILIO['auth_token'])

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
            except BaseException as err:
                e = 'Error occured while watching event: %s', err
                logging.debug(e)
                TWILIO_CLIENT.messages.create(from_=TWILIO['from_num'], to=TWILIO['to_num'], body='Error watching event')

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
        self.new_contributor = False
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
                self.new_contributor = True
            elif num_patches > 5:
                self.rising_contributor = True
        except BaseException as err:
            e = 'Error occured while identifying patch owner: %s', err
            logging.debug(e)
            TWILIO_CLIENT.messages.create(from_=TWILIO['from_num'], to=TWILIO['to_num'], body=e)

    def is_first_time_contributor(self):
        """ Returns first_time_contributor as boolean
        """
        return self.first_time_contributor

    def is_new_contributor(self):
        """ Returns new_contributor as boolean
        """
        return self.new_contributor

    def is_rising_contributor(self):
        """ Returns rising_contributor as boolean
        """
        return self.rising_contributor

    def add_reviewer_and_comment(self, change_id, cur_rev):
        """ Adds a reviewer "First-time-contributor" and welcome message
        to a patch
        """
        try:
            if not self.is_reviewer_added_already(change_id):
                query = "/changes/" + str(change_id) + "/revisions/" + str(cur_rev) + "/review"
                REST_CLIENT.post(query, json={
                    "message": self.fetch_welcome_message()
                })
        except BaseException as err:
            e = 'Error occured while adding reviewer and welcome comment: %s', err
            logging.debug(e)
            TWILIO_CLIENT.messages.create(from_=TWILIO['from_num'], to=TWILIO['to_num'], body=e)

    def add_to_group(self, username):
        """ Adds newcomer to a group
        """
        try:
            query_add_member = "/groups/" + MISC['newcomer_group'] + \
                "/members/" + username
            REST_CLIENT.put(query_add_member)
        except BaseException as err:
            e = 'Error occured while adding newcomer to group: %s', err
            logging.debug(e)
            TWILIO_CLIENT.messages.create(from_=TWILIO['from_num'], to=TWILIO['to_num'], body=e)

    def remove_from_group(self, username):
        """ Removes newcomer from a group
        """
        try:
            if self.is_rising_contributor_in_group(username):
                query_del_member = "/groups/" + MISC['newcomer_group'] + \
                    "/members/" + username
                REST_CLIENT.delete(query_del_member)
        except BaseException as err:
            e = 'Error occured while removing newcomer from group: %s', err
            logging.debug(e)
            TWILIO_CLIENT.messages.create(from_=TWILIO['from_num'], to=TWILIO['to_num'], body=e)

    def is_rising_contributor_in_group(self, username):
        """ Check if rising contributor is member of newcomer group
        """
        try:
            query_ls_members = "/groups/" + MISC['newcomer_group'] + \
                "/members/"
            group_members = REST_CLIENT.get(query_ls_members)
            num_of_members = len(group_members)

            for i in range(num_of_members):
                if username == group_members[i]['username']:
                    return True
            return False
        except BaseException as err:
            e = 'Error listing members of newcomer group: %s', err
            logging.debug(e)
            TWILIO_CLIENT.messages.create(from_=TWILIO['from_num'], to=TWILIO['to_num'], body=e)

    def is_reviewer_added_already(self, change_id):
        """ Check if newcomer bot is already added as a reviewer to a patch
        """
        try:
            query_change_details = "/changes/" + str(change_id) + "/detail"
            change_details = REST_CLIENT.get(query_change_details)
            reviewers = change_details["removable_reviewers"]
            num_of_reviewers = len(reviewers)

            for i in range(num_of_reviewers):
                if MISC['auth_username'] == reviewers[i]['username']:
                    return True
            return False
        except BaseException as err:
            e = 'Error occured while querying change details: %s', err
            logging.debug(e)
            TWILIO_CLIENT.messages.create(from_=TWILIO['from_num'], to=TWILIO['to_num'], body=e)

    def fetch_welcome_message(self):
        """ Fetch welcome message from a remote wiki page
        """
        # build the API request url
        url = "https://www.mediawiki.org/w/index.php?title=" + \
            MISC['welcome_message_page']  + "&action=raw"
        response = requests.get(url)
        content = response.text
        # remove tags
        content = re.compile(r'<.*?>').sub('', content)
        return content

def main(event):
    """ Invokes functions of class 'WelcomeNewcomersAndGroupThem'
    """
    logging.info('Patch details: %s', event)

    username = event['patchSet']['author']['username']
    change_id = event['change']['id']
    revision = event['patchSet']['revision']

    newcomer = WelcomeNewcomersAndGroupThem()
    newcomer.identify(username)

    logging.info('Patch has been uploaded by user: %s', username)

    if newcomer.is_first_time_contributor():
        logging.info('Patch owner is a first time contributor')
        newcomer.add_reviewer_and_comment(change_id, revision)
        newcomer.add_to_group(username)

    if newcomer.is_new_contributor():
        logging.info('Patch owner is a new contributor')
        newcomer.add_to_group(username)

    if newcomer.is_rising_contributor():
        logging.info('Patch owner is a rising contributor')
        newcomer.remove_from_group(username)

STREAM = WatchPatchsets()
STREAM.daemon = True
STREAM.start()
while True:
    EVENT = QUEUE.get()
    if EVENT:
        main(EVENT)

STREAM.join()
