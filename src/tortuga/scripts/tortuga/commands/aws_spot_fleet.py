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
import boto3
import argparse

from tortuga.cli.base import Command, Argument
from ....resourceAdapter.aws.helpers import get_redis_client, get_region


REDIS_CLIENT = get_redis_client()
REDIS_KEY = 'tortuga-aws-splot-fleet-requests'
BOTO = boto3.client('ec2', region_name=get_region())


class ListSpotFleet(Command):
    """
    List spot fleet requests.
    """
    name = 'list'
    help = 'List spot fleet requests'

    def execute(self, args: argparse.Namespace):
        """
        Print list of spot fleet
        requests.

        :param args: Namespace
        :returns: None
        """
        for sfr_id in REDIS_CLIENT.hkeys(REDIS_KEY):
            target: str = REDIS_CLIENT.hget(REDIS_KEY, sfr_id)
            print(f'ID: {sfr_id.decode()} TARGET: {target.decode()}')


class DeleteSpotFleet(Command):
    """
    Deletes spot fleet requets.
    """
    name = 'delete'
    help = 'Delete spot fleet request'

    arguments = [
        Argument(
            'id',
            help='Spot fleet request ID'
        )
    ]

    def execute(self, args: argparse.Namespace):
        """
        Delete spot fleet request.

        :param args: Namespace
        :returns: None
        """
        BOTO.cancel_spot_fleet_requests(
            DryRun=False,
            SpotFleetRequestIds=[
                args.id,
            ],
            TerminateInstances=True
        )
        REDIS_CLIENT.hdel(
            REDIS_KEY,
            args.id
        )


class SetSpotFleet(Command):
    """
    Set the spot fleet request
    target.
    """
    name = 'set'
    help = 'Set target for spot fleet request'

    arguments = [
        Argument(
            'id',
            help='Spot fleet request ID'
        ),
        Argument(
            'target',
            help='Instance target',
            type=int
        )
    ]

    def execute(self, args: argparse.Namespace):
        """
        Set spot fleet request
        target instances.

        :param args: Namespace
        :returns: None
        """
        BOTO.modify_spot_fleet_request(
            SpotFleetRequestId=args.id,
            TargetCapacity=args.target
        )
        REDIS_CLIENT.hset(
            REDIS_KEY,
            args.id,
            args.target
        )

class SpotFleetRootCommand(Command):
    """
    Hold the subcommands for spot
    fleet.
    """
    name = 'fleet'
    help = 'Spot fleet actions'

    sub_commands = [
        ListSpotFleet(),
        DeleteSpotFleet(),
        SetSpotFleet()
    ]
