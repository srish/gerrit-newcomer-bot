import configparser
import queue
import json
import logging
import threading
import time
import paramiko

queue = queue.Queue()

# Logging
logging.basicConfig(level=logging.INFO)
logger = paramiko.util.logging.getLogger()
logger.setLevel(logging.INFO)

# Config
config = configparser.ConfigParser()
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

bot = dict(timeout=10)
bot.update(config.items('Bot'))

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
                    row_count = json_data.get("rowCount")

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
                + project + ' -a ' + bot['reviewer_bot'] + ' ' + change_id
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
            cmd_review = 'gerrit review -m "' + bot['welcome_message'] + '" ' + cur_rev
            client.exec_command(cmd_review)
        except BaseException:
            logging.exception('Gerrit error')

    def add_newcomer_to_group(self, submitter):
        try:
            cmd_add_member = 'gerrit set-members -a {} {}'.format(
                submitter, bot['newcomer_group'])
            client.exec_command(cmd_add_member)
        except BaseException:
            logging.exception('Gerrit error')

    def remove_newcomer_from_group(self, submitter):
        try:
            cmd_remove_member = 'gerrit set-members -r {} {}'.format(
                submitter, bot['newcomer_group'])
            client.exec_command(cmd_remove_member)
        except BaseException:
            logging.exception('Gerrit error')


def main(submitter):
    newcomer = WelcomeNewcomersAndGroupThem()
    newcomer.identify(submitter)

    first_time_contributor = newcomer.getis_first_time_contributor()
    if first_time_contributor:
        cur_patch = newcomer.get_current_patchset(submitter)

        project = cur_patch.get("project")
        change_id = cur_patch.get("id")
        cur_rev = cur_patch.get("currentPatchSet").get("revision")

        newcomer.add_reviewer(project, change_id)
        newcomer.add_comment(cur_rev)

    new_contributor = newcomer.getis_new_contibutor()
    if new_contributor or first_time_contributor:
        newcomer.add_newcomer_to_group(submitter)

    rising_contributor = newcomer.getis_rising_contributor()
    if rising_contributor:
        newcomer.remove_newcomer_from_group(submitter)


# From https://stackoverflow.com/a/9807955
def find_submitter_key(key, dictionary):
    for k, v in dictionary.items():
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
    submitter = submitter_list[:][0]
    return submitter


if __name__ == '__main__':
    stream = WatchPatchsets()
    stream.daemon = True
    stream.start()

    while True:
        event = queue.get()
        if event:
            submitter_list = list(find_submitter_key('username', event))
            submitter = get_submitter(submitter_list)
            main(submitter)

    stream.join()
