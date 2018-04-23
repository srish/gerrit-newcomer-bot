import configparser
import queue
import json
import logging
import threading
import time
import paramiko
import requests
import pygerrit2

from requests.auth import HTTPBasicAuth
from pygerrit2.rest import GerritRestAPI

queue = queue.Queue()

# Logging
logging.basicConfig(level=logging.INFO)
logger = paramiko.util.logging.getLogger()
logger.setLevel(logging.INFO)

# Load configuration
config = configparser.ConfigParser()
config.read('gerrit.conf')

gerrit_ssh = dict()
gerrit_ssh.update(config.items('Gerrit SSH'))
gerrit_ssh['port'] = int(gerrit_ssh['port'])
gerrit_ssh['timeout'] = int(gerrit_ssh['timeout'])

misc = dict()
misc.update(config.items('Misc'))

# Paramiko client
client = paramiko.SSHClient()
client.load_system_host_keys()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(**gerrit_ssh)

class WatchPatchsets(threading.Thread):
    def run(self):
        while True:
            try:
                cmd_patchset_created = 'gerrit stream-events -s patchset-created'
                _, stdout, _ = client.exec_command(cmd_patchset_created)
                for line in stdout:
                    queue.put(json.loads(line))
            except BaseException:
                logging.exception('Gerrit error')
            finally:
                client.close()
            time.sleep(5)


class WelcomeNewcomersAndGroupThem():
    def __init__(self):
        self.new_contibutor = False
        self.first_time_contributor = False
        self.rising_contributor = False
        self.rest_client = self.get_rest_client()

    def identify(self, submitter):
        try:
            patches_by_owner = self.rest_client.get("/changes/?q=owner:" + submitter)
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
        return self.first_time_contributor

    def is_new_contibutor(self):
        return self.new_contibutor

    def is_rising_contributor(self):
        return self.rising_contributor

    def add_reviewer_and_comment(self, change_id, cur_rev):
        try:
            query = "/changes/" + str(change_id) + "/revisions/" + str(cur_rev) + "/review"
            self.rest_client.post(query, 
                json={
                "message": misc['welcome_message'],
                "reviewers": [{
                    "reviewer": misc['reviewer_bot']
                    }]
            })  
        except BaseException:
            logging.exception('Gerrit error')

    def add_to_group(self, username):
        try:
            query_add_member = "/groups/" + misc['newcomer_group'] + \
                "/members/" + username
            self.rest_client.put(query_add_member)
        except BaseException:
            logging.exception('Gerrit error')

    def remove_from_group(self, username):
        try:
            query_del_member = "/groups/" + misc['newcomer_group'] + \
                "/members/" + username
            self.rest_client.delete(query_del_member)
        except BaseException:
            logging.exception('Gerrit error')

    def get_rest_client(self):
        try:
            auth = HTTPBasicAuth(misc['auth_username'], misc['auth_password'])
            rest = GerritRestAPI(url=misc['base_url'], auth=auth)
            return rest
        except BaseException:
            logging.exception('Gerrit client error')


def main(username, change_id, revision):
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
    stream = WatchPatchsets()
    stream.daemon = True
    stream.start()
    
    while True:
        event = queue.get()
        if event:
            username = event['change']['owner']['username']
            change_id = event['change']['id']
            revision = event['patchSet']['revision']

            main(username, change_id, revision)

    stream.join()
