#!/usr/bin/env python

# Copyright 2008-2018 Univa Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import logging
import optparse
import sys
import threading
import redis
import boto
import boto.ec2
import boto3

from time import sleep
from daemonize import Daemonize
from subprocess import check_output
from tortuga.exceptions.nodeAlreadyExists import NodeAlreadyExists
from tortuga.wsapi.addHostWsApi import AddHostWsApi


PIDFILE = '/var/log/fleetspotd.pid'

FACTER_PATH = '/opt/puppetlabs/bin/facter'


def get_redis_client():
    try:
        uri = check_output(
            [FACTER_PATH, 'redis_url']
        ).strip().decode()
    except:
        uri = None

    if not uri:
        uri = 'localhost:6379'

    host, port = uri.split(':')

    return redis.StrictRedis(
        host=host,
        port=int(port),
        db=0
    )


REDIS_CLIENT = get_redis_client()


def spot_listener(logger, ec2):
    logger.info('Starting spot listener thread')

    pubsub = REDIS_CLIENT.pubsub()
    pubsub.subscribe('tortuga-aws-spot-d')

    while True:
        request = pubsub.get_message()

        if request and request['type'] == 'message' and request['data']:
            try:
                data = json.loads(request['data'])
            except Exception:
                continue

            if 'action' not in data:
                continue

            try:
                result = ec2.get_all_spot_instance_requests(
                    request_ids=data['spot_instance_request_id']
                )
            except boto.exception.EC2ResponseError as exc:
                if exc.status == 400 and \
                        exc.error_code == \
                        u'InvalidSpotInstanceRequestID.NotFound':
                    logger.warning(
                        '{} is an invald SIR'.format(
                            data['spot_instance_request_id']
                        )
                    )
                    continue

            result = result[0]

            if result.state == 'active' and \
                    result.status.code == 'fulfilled':

                instances = ec2.get_all_instances(
                    instance_ids=[result.instance_id]
                )
                instance = instances[0].instances[0]

                logger.debug(
                    'Queuing add of {}'.format(
                        instance.private_dns_name
                    )
                )

                REDIS_CLIENT.hset(
                    'tortuga-aws-spot-fulfill',
                    data['spot_instance_request_id'],
                    json.dumps({
                        'name': instance.private_dns_name,
                        'id': instance.id,
                        'private_ip_address': instance.private_ip_address
                    })
                )


def poll_for_spot_instances(logger, request, ec2_client):
    enqueued = []

    while True:
        logger.debug(
            'SIR queue {} of {}'.format(
                len(enqueued),
                request['target']
            )
        )
        if request['target'] == len(enqueued):
            logger.info(
                'Finished queueing {} requests'.format(request['target'])
            )
            break

        response = ec2_client.describe_spot_fleet_instances(
            SpotFleetRequestId=request['spot_fleet_request_id']
        )

        if response['ActiveInstances']:
            for instance in response['ActiveInstances']:
                if instance['SpotInstanceRequestId'] not in enqueued:
                    REDIS_CLIENT.publish(
                        'tortuga-aws-spot-d',
                        json.dumps({
                            'action': 'add',
                            'spot_instance_request_id': instance['SpotInstanceRequestId'],
                            'softwareprofile': request['softwareprofile'],
                            'hardwareprofile': request['hardwareprofile']
                        })
                    )

                    enqueued.append(instance['SpotInstanceRequestId'])

        sleep(5)


def glide_to_target(spot_fleet_request_id, initial, target, logger,
                    ec2_client):
    current = initial
    while current < target:
        request = ec2_client.describe_spot_fleet_requests(
            SpotFleetRequestIds=[spot_fleet_request_id]
        )['SpotFleetRequestConfigs'][0]

        if request['SpotFleetRequestState'] == 'active':
            if (target - current) >= 250:
                current += 250
            else:
                current += (target - current)

            logger.debug(
                'Increasing spot fleet request to {} of {}'.format(
                    current,
                    target
                )
            )

            ec2_client.modify_spot_fleet_request(
                SpotFleetRequestId=spot_fleet_request_id,
                TargetCapacity=current
            )

        sleep(5)


def poll_fulfilled_requests(logger):
    logger.info('Starting fulfillment thread')
    while True:
        requests = REDIS_CLIENT.hgetall('tortuga-aws-spot-fulfill')
        if not requests:
            sleep(5)
            continue
        add_nodes_request = {
            'softwareProfile': REDIS_CLIENT.get(
                'tortuga-aws-spot-software-profile').decode(),
            'hardwareProfile': REDIS_CLIENT.get(
                'tortuga-aws-spot-hardware-profile').decode(),
            'isIdle': False,
            'count': len(requests.keys()),
            'nodeDetails': [],
        }

        resource_adapter_configuration = REDIS_CLIENT.get(
            'tortuga-aws-spot-resource-adapter-configuration'
        )

        if resource_adapter_configuration:
            add_nodes_request['resource_adapter_configuration'] = \
                json.loads(resource_adapter_configuration)

        for sir_id, instance in requests.items():
            instance = json.loads(instance)
            add_nodes_request['nodeDetails'].append({
                'name': instance['name'],
                'metadata': {
                    'ec2_instance_id': instance['id'],
                    'ec2_ipaddress': instance['private_ip_address'],
                }
            })
            REDIS_CLIENT.hdel(
                'tortuga-aws-spot-fulfill',
                sir_id
            )

        logger.debug(
            'Adding {} nodes to Tortuga'.format(
                len(add_nodes_request['nodeDetails'])
            )
        )

        try:
            AddHostWsApi().addNodes(add_nodes_request)
        except NodeAlreadyExists as e:
            logger.error(e)

        sleep(5)


def spot_fleet_listener(logger, ec2_client):
    logger.info('Starting spot fleet listener thread')

    pubsub = REDIS_CLIENT.pubsub()
    pubsub.subscribe('tortuga-aws-spot-fleet-d')

    while True:
        request = pubsub.get_message()

        if request and request['type'] == 'message' and request['data']:
            try:
                data = json.loads(request['data'])
            except Exception:
                continue

            logger.debug('Got fleet request {}'.format(
                data['spot_fleet_request_id']
            ))

            REDIS_CLIENT.set(
                'tortuga-aws-spot-software-profile',
                data['softwareprofile']
            )

            REDIS_CLIENT.set(
                'tortuga-aws-spot-hardware-profile',
                data['hardwareprofile']
            )

            if 'spot_fleet_request_id' in data:
                if data['target'] > 250:
                    glide_thread = threading.Thread(
                        target=glide_to_target,
                        args=(
                            data['spot_fleet_request_id'],
                            250,
                            data['target'],
                            logger,
                            ec2_client
                        ),
                        daemon=True
                    )
                    glide_thread.start()

                poll_for_spot_instances(
                    logger,
                    data,
                    ec2_client
                )


class FleetSpotdAppClass(object):
    def __init__(self, options, args):
        self.options = options
        self.args = args

        self.logger = None

    def run(self):
        # Ensure logger is instantiated _after_ process is daemonized
        self.logger = logging.getLogger('tortuga.aws.fleetspotd')

        self.logger.setLevel(logging.DEBUG)

        # create console handler and set level to debug
        ch = logging.handlers.TimedRotatingFileHandler(
            '/var/log/tortuga_fleetspotd',
            when='midnight'
        )

        ch.setLevel(logging.DEBUG)

        # create formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s')

        # add formatter to ch
        ch.setFormatter(formatter)

        # add ch to logger
        self.logger.addHandler(ch)

        self.logger.info(
            'Starting... EC2 region [{0}]'.format(
                self.options.region
            )
        )

        boto_client = boto.ec2.connect_to_region(self.options.region)
        boto3_client = boto3.client('ec2', region_name=self.options.region)

        threads = []

        spot_listener_thread = threading.Thread(
            target=spot_listener,
            args=(self.logger, boto_client),
            daemon=True
        )
        spot_listener_thread.start()
        threads.append(spot_listener_thread)

        spot_fleet_thread = threading.Thread(
            target=spot_fleet_listener,
            args=(self.logger, boto3_client),
            daemon=True
        )
        spot_fleet_thread.start()
        threads.append(spot_fleet_thread)

        fulfilled_thread = threading.Thread(
            target=poll_fulfilled_requests,
            args=(self.logger,),
            daemon=True
        )
        fulfilled_thread.start()
        threads.append(fulfilled_thread)

        [t.join() for t in threads]


def main():
    parser = optparse.OptionParser()

    aws_group = optparse.OptionGroup(parser, 'AWS Options')

    aws_group.add_option(
        '--region',
        default=None,
        help='AWS region to manage Spot Instances in'
    )

    parser.add_option_group(aws_group)

    parser.add_option(
        '--verbose',
        action='store_true',
        default=False,
        help='Enable verbose logging'
    )

    parser.add_option(
        '--daemon',
        action='store_false',
        dest='foreground',
        default=True,
        help='Start awsspotd in the background'
    )

    parser.add_option(
        '--pidfile',
        default=PIDFILE,
        help='Location of PID file'
    )

    options_, args_ = parser.parse_args()

    try:
        if not options_.region:
            az = check_output(
                [
                    FACTER_PATH,
                    '--no-external-facts',
                    'ec2_metadata.placement.availability-zone'
                ]
            ).strip().decode()

            options_.region = az[:-1]

    except Exception:
        options_.region = 'us-west-1'

    result_ = [region for region in boto.ec2.regions()
               if region.name == options_.region]

    if not result_:
        sys.stderr.write(
            'Error: Invalid EC2 region [{0}] specified\n'.format(
                options_.region))
        sys.exit(1)

    cls = FleetSpotdAppClass(options_, args_)

    daemon = Daemonize(
        app='fleetspotd',
        pid=options_.pidfile,
        action=cls.run,
        verbose=options_.verbose,
        foreground=options_.foreground
    )

    daemon.start()
