#!/usr/bin/env python
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
newcomerGroup = "NEWCOMERS"


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


class WelcomeFirsttimers():
    def __init__(self):
        self.is_new_contibutor = False
        self.is_first_time_contributor = False
        self.is_rising_contributor = False

    def identify(self, submitter):
        try:
            cmd_query_patches_by_owner = 'gerrit query --format=JSON owner:"' \
                + submitter + '"'
            _, stdout, _ = client.exec_command(cmd_query_patches_by_owner)

            row_count = 0
            lines = stdout.readlines()
            num_lines = len(lines)

            if num_lines >= 1:
                json_data = json.loads(lines[num_lines - 1])
                if json_data:
                    row_count = json_data.get("row_count")

            if row_count == 1:
                self.is_first_time_contributor = True
            elif row_count > 0 and row_count <= 5:
                self.is_new_contibutor = True
            elif row_count > 5:
                self.is_rising_contributor = True
        except BaseException:
            logging.exception('Gerrit error')

    def getis_first_time_contributor(self):
        return self.is_first_time_contributor

    def getis_new_contibutor(self):
        return self.is_new_contibutor

    def getis_rising_contributor(self):
        return self.is_rising_contributor

    def add_reviewer(self, project, change_id):
        try:
            cmd_set_reviewers = 'gerrit set-reviewers --project ' \
                + project + ' -a ' + reviewerBot + ' ' + change_id
            client.exec_command(cmd_set_reviewers)
        except BaseException:
            logging.exception('Gerrit error')

    def get_current_patchset(self, submitter):
        try:
            cmd_query_cur_patch_set = 'gerrit query --format=JSON --current-patch-set owner:' \
                + submitter
            _, stdout, _ = client.exec_command(cmd_query_cur_patch_set)
            lines = stdout.readlines()

            if lines[0]:
                cur_patch = json.loads(lines[0])
                return cur_patch
            return
        except BaseException:
            logging.exception('Gerrit error')

    def add_comment(self, cur_rev):
        try:
            cmd_review = 'gerrit review -m "' + welcomeMessage + '" ' + cur_rev
            client.exec_command(cmd_review)
        except BaseException:
            logging.exception('Gerrit error')


class GroupNewcomers():
    def does_newcomer_group_exist(self):
        try:
            cmd_ls_groups = 'gerrit ls-groups'
            _, stdout, _ = client.exec_command(cmd_ls_groups)
            lines = stdout.readlines()

            for i in range(len(lines)):
                if newcomerGroup in lines[i]:
                    return True
            return False
        except BaseException:
            logging.exception('Gerrit error')

    def create_newcomer_group(self):
        try:
            cmd_create_group = 'gerrit create-group ' + newcomerGroup
            client.exec_command(cmd_create_group)
        except BaseException:
            logging.exception('Gerrit error')

    def add_newcomer_to_group(self, submitter):
        try:
            cmd_add_member = 'gerrit set-members -a {} {}'.format(
                submitter, newcomerGroup)
            client.exec_command(cmd_add_member)
        except BaseException:
            logging.exception('Gerrit error')

    def remove_newcomer_from_group(self, submitter):
        try:
            cmd_remove_member = 'gerrit set-members -r {} {}'.format(
                submitter, newcomerGroup)
            client.exec_command(cmd_remove_member)
        except BaseException:
            logging.exception('Gerrit error')


def welcome_newcomers_and_group_them(newcomer):
    first_timer = WelcomeFirsttimers()
    group = GroupNewcomers()
    first_timer.identify(newcomer)

    first_time_contributor = first_timer.getis_first_time_contributor()
    if first_time_contributor:
        cur_patch = first_timer.get_current_patchset(newcomer)

        project = cur_patch.get("project")
        change_id = cur_patch.get("id")
        cur_rev = cur_patch.get("currentPatchSet").get("revision")

        first_timer.add_reviewer(project, change_id)
        first_timer.add_comment(cur_rev)

    new_contributor = first_timer.getis_new_contibutor()
    if new_contributor:
        new_group_exists = group.does_newcomer_group_exist()
        if not new_group_exists:
            group.create_newcomer_group()
        group.add_newcomer_to_group(newcomer)

    rising_contributor = first_timer.getis_rising_contributor()
    if rising_contributor:
        group.remove_newcomer_from_group(newcomer)


# From https://stackoverflow.com/a/9807955
def find_submitter_key(key, dictionary):
    for k, v in dictionary.iteritems():
        if k == key:
            yield v
        elif isinstance(v, dict):
            for result in find_submitter_key(key, v):
                yield result
        elif isinstance(v, list):
            for d in v:
                if isinstance(d, dict):
                    for result in find_submitter_key(key, d):
                        yield result


def get_submitter(submitter_list):
    submitter_list[:] = [item for item in submitter_list if item != '']
    newcomer = submitter_list[:][0]
    return newcomer


if __name__ == '__main__':
    stream = WatchPatchsets()
    stream.daemon = True
    stream.start()

    while True:
        event = queue.get()
        if event:
            submitter_list = list(find_submitter_key('username', event))
            newcomer = get_submitter(submitter_list)
            welcome_newcomers_and_group_them(newcomer)

    stream.join()
