#!/usr/bin/env python
# Uses py-smartdc fork in https://github.com/ahelal/py-smartdc.git

import os
import sys
import ConfigParser
from datetime import datetime

__DEFAULT_CACHE_FILE__ = "/tmp/ansible_inventory_joyent.cache"
__DEFAULT_PID_FILE__ = "/tmp/ansible_inventory_joyent.pid"
__DEFAULT_ENV_PREFIX__ = "JOYENT_INV_"
__DEFAULT_CACHE_EXPIRE__ = 300
__DEFAULT_URL__ = "east-1.api.joyentcloud.com"
__DEFAULT_AUTH_KEY__ = "~/.ssh/id_rsa"

try:
    import json
except ImportError:
    import simplejson as json


def safe_fail_stderr(msg):
    # Print error and dont break ansible by printing an emtpy JSON
    print >> sys.stderr, msg
    print json.dumps(json.loads("{}"), indent=4, sort_keys=True)
    sys.exit(1)

try:
    from smartdc import DataCenter
except ImportError:
    # Print error but dont break ansible inventory
    safe_fail_stderr("Cant import DataCenter. Please install smartdc")


class JoyentInventory(object):
    def __init__(self):
        self.inventory = {}
        self.__get_config__()
        self.pid_file = __DEFAULT_PID_FILE__
        self.tag_ignore = ["provisioner_ver", "provisioner"]

    def __get_config__(self):
        # Read config
        self.config = ConfigParser.SafeConfigParser()
        my_name = os.path.abspath(sys.argv[0]).rstrip('.py')
        path_search = [my_name + '.ini', 'joyent.ini']
        for config_filename in path_search:
            if os.path.exists(config_filename):
                self.config.read(config_filename)
                break

        self.cache_enable = self._get_config('cache_enable', 'cache', fail_if_not_set=False, default_value="true").lower() \
                             in ['true', '1', 't', 'y', 'yes', 'yeah']

        self.cache_smart = self._get_config('cache_smart', 'cache', fail_if_not_set=False, default_value="true").lower() \
                             in ['true', '1', 't', 'y', 'yes', 'yeah']

        self.cache_expire = int(self._get_config('cache_expire', 'cache', fail_if_not_set=False, default_value=300))
        self.cache_file = self._get_config('cache_file', 'cache', fail_if_not_set=False, default_value=__DEFAULT_CACHE_FILE__)
        self.joyent_uri = self._get_config('uri', 'api', fail_if_not_set=False, default_value=__DEFAULT_URL__)
        self.joyent_secret = self._get_config('auth_key', 'auth', fail_if_not_set=False, default_value=__DEFAULT_AUTH_KEY__)
        self.joyent_username = self._get_config('auth_username', 'auth', fail_if_not_set=True)
        self.joyent_key_name = self._get_config('auth_key_name', 'auth', fail_if_not_set=True)
        self.debug = self._get_config('debug', 'defaults', fail_if_not_set=False)
        # Compile key id
        self.joyent_key_id = "/" + self.joyent_username + "/keys/" + self.joyent_key_name

    def _get_config(self, value, section, fail_if_not_set=True, default_value=None):
        # Env variable always win
        if os.getenv(__DEFAULT_ENV_PREFIX__ + value.upper(), False):
            return os.getenv(__DEFAULT_ENV_PREFIX__ + value.upper())
        try:
            if self.config.get(section, value, vars=False):
                return self.config.get(section, value)
        except ConfigParser.NoOptionError:
            pass
        except ConfigParser.NoSectionError:
            pass

        if fail_if_not_set:
            print "Failed to get setting for '{}' from ini file or '{}' from env variable."\
                .format(value, __DEFAULT_ENV_PREFIX__ + value.upper())
            exit(1)
        else:
            return default_value

    def check_cache(self):
        ''' Checks if we can server from cache or API call '''

        try:
            stats = os.stat(self.cache_file)
        except:
            # No cache or cant read just get from API
            return self.build_inv_from_api()

        seconds_since_last_modified = (datetime.now() - datetime.fromtimestamp(stats.st_mtime)).total_seconds()
        if seconds_since_last_modified < self.cache_expire and self.cache_enable:
            # Get data from cache
            self.read_cache()
        else:
            if self.cache_smart:
                # Get data from cache
                self.read_cache()
            else:
                # Get data from API
                self.build_inv_from_api()

    def build_inv_from_api(self):
        servers = self.api_get()
        self.inventory["all"] = {'hosts': [], 'vars': {}}
        self.inventory['_meta'] = {'hostvars': {}}

        for server in servers:
            self.inventory["all"]["hosts"].append(server.name)
            self.inventory['_meta']['hostvars'][server.name] = {}
            self.inventory['_meta']['hostvars'][server.name]['type'] = server.type
            self.inventory['_meta']['hostvars'][server.name]['brand'] = server.brand
            self.inventory['_meta']['hostvars'][server.name]['memory'] = server.memory
            self.inventory['_meta']['hostvars'][server.name]['disk'] = server.disk
            self.inventory['_meta']['hostvars'][server.name]['image'] = server.image
            self.inventory['_meta']['hostvars'][server.name]['package'] = server.package
            self.inventory['_meta']['hostvars'][server.name]['compute_node'] = server.compute_node
            try:
                self.inventory['_meta']['hostvars'][server.name]['ansible_host'] = server.primaryIp
            except AttributeError:
                pass
            if server.type == "smartmachine":
                self.inventory['_meta']['hostvars'][server.name]['ansible_python_interpreter'] = "/opt/local/bin/python"

        self.save_cache()

    def api_get(self):
        """ Ask Joyent for all servers in a data center"""
        sdc = DataCenter(location=self.joyent_uri, key_id=self.joyent_key_id, secret=self.joyent_secret,
                         allow_agent=False, verbose=self.debug)
        servers = sdc.machines()
        return servers

    def read_cache(self):
        try:
            with open(self.cache_file, 'r') as f:
                self.inventory = json.load(f)
        except IOError, e:
            safe_fail_stderr("read cache IO Error")

    def save_cache(self):
        try:
            with open(self.cache_file, 'w') as f:
                json.dump(self.inventory, f)
        except IOError, e:
            safe_fail_stderr("save cache IO Error")

    def main(self):
        # Command line parser
        if len(sys.argv) == 2 and (sys.argv[1] == '--list'):
            self.check_cache()
            print json.dumps(self.inventory, indent=4)
        elif len(sys.argv) == 2 and (sys.argv[1] == '--host'):
            self.check_cache()
            print json.dumps(self.inventory["hosts"][sys.argv[2]], indent=4)
        elif len(sys.argv) == 2 and (sys.argv[1] == '--debug'):
            self.check_cache()
            print "debug=", self.debug
            print "Groups"
            for group in self.inventory:
                print " _ " + group
            #print json.dumps(self.inventory["hosts"][sys.argv[2]], indent=4)
        else:
            print "Usage: %s --list or --host <hostname>" % sys.argv[0]
            sys.exit(1)
        sys.stdout.flush()
        sys.stderr.flush()

        sys.exit(0)


if __name__ == '__main__':
    JoyentInventory().main()
