#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.
#

import json
import logging
import random
import string
import subprocess


LOG = logging.getLogger(__name__)


class DockerRunner(object):

    def __init__(self, managed_by, docker_cmd=None):
        self.managed_by = managed_by
        self.docker_cmd = docker_cmd or 'docker'

    @staticmethod
    def execute(cmd):
        LOG.debug(' '.join(cmd))
        subproc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
        cmd_stdout, cmd_stderr = subproc.communicate()
        LOG.debug(cmd_stdout)
        LOG.debug(cmd_stderr)
        return cmd_stdout, cmd_stderr, subproc.returncode

    def current_config_ids(self):
        # List all config_id labels for managed containers
        cmd = [
            self.docker_cmd, 'ps', '-a',
            '--filter', 'label=managed_by=%s' % self.managed_by,
            '--format', '{{.Label "config_id"}}'
        ]
        cmd_stdout, cmd_stderr, returncode = self.execute(cmd)
        if returncode != 0:
            return set()
        return set(cmd_stdout.split())

    def remove_containers(self, conf_id):
        cmd = [
            self.docker_cmd, 'ps', '-q', '-a',
            '--filter', 'label=managed_by=%s' % self.managed_by,
            '--filter', 'label=config_id=%s' % conf_id
        ]
        cmd_stdout, cmd_stderr, returncode = self.execute(cmd)
        if returncode == 0:
            for container in cmd_stdout.split():
                self.remove_container(container)

    def remove_container(self, container):
        cmd = [self.docker_cmd, 'rm', '-f', container]
        cmd_stdout, cmd_stderr, returncode = self.execute(cmd)
        if returncode != 0:
            LOG.error('Error removing container: %s' % container)
            LOG.error(cmd_stderr)

    def rename_containers(self):
        # list every container name, and its container_name label
        cmd = [
            self.docker_cmd, 'ps', '-a',
            '--filter', 'label=managed_by=%s' % self.managed_by,
            '--format', '{{.Names}} {{.Label "container_name"}}'
        ]
        cmd_stdout, cmd_stderr, returncode = self.execute(cmd)
        if returncode != 0:
            return

        lines = cmd_stdout.split("\n")
        current_containers = []
        need_renaming = {}
        for line in lines:
            entry = line.split()
            if not entry:
                continue
            current_containers.append(entry[0])

            # ignore if container_name label not set
            if len(entry) < 2:
                continue

            # ignore if desired name is already actual name
            if entry[0] == entry[-1]:
                continue

            need_renaming[entry[0]] = entry[-1]

        for current, desired in sorted(need_renaming.items()):
            if desired in current_containers:
                LOG.info('Cannot rename "%s" since "%s" still exists' % (
                    current, desired))
            else:
                self.rename_container(current, desired)

    def rename_container(self, container, name):
        cmd = [self.docker_cmd, 'rename', container, name]
        cmd_stdout, cmd_stderr, returncode = self.execute(cmd)
        if returncode != 0:
            LOG.error('Error renaming container: %s' % container)
            LOG.error(cmd_stderr)

    def inspect(self, container, format=None):
        cmd = [self.docker_cmd, 'inspect']
        if format:
            cmd.append('--format')
            cmd.append(format)
        cmd.append(container)
        (cmd_stdout, cmd_stderr, returncode) = self.execute(cmd)
        if returncode != 0:
            return
        try:
            if format:
                return cmd_stdout
            else:
                return json.loads(cmd_stdout)[0]
        except Exception as e:
            LOG.error('Problem parsing docker inspect: %s' % e)

    def unique_container_name(self, container):
        container_name = container
        while self.inspect(container_name, format='exists'):
            suffix = ''.join(random.choice(
                string.ascii_lowercase + string.digits) for i in range(8))
            container_name = '%s-%s' % (container, suffix)
        return container_name

    def discover_container_name(self, container, cid):
        cmd = [
            self.docker_cmd,
            'ps',
            '-a',
            '--filter',
            'label=container_name=%s' % container,
            '--filter',
            'label=config_id=%s' % cid,
            '--format',
            '{{.Names}}'
        ]
        (cmd_stdout, cmd_stderr, returncode) = self.execute(cmd)
        if returncode != 0:
            return container
        names = cmd_stdout.split()
        if names:
            return names[0]
        return container

    def delete_missing_configs(self, config_ids):
        for conf_id in self.current_config_ids():
            if conf_id not in config_ids:
                LOG.debug('%s no longer exists, deleting containers' % conf_id)
                self.remove_containers(conf_id)
