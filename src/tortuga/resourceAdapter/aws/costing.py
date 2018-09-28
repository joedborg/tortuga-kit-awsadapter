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
from datetime import date
from typing import Generator, Optional
from tortuga.resourceAdapter.costing import Costing


class AwsCosting(Costing):
    """
    Handle costing of AWS.
    """
    def __init__(self, start: date, end: date) -> None:
        """

        :param start: Datetime start of report
        :param end: Datetime end of report
        :returns: None
        """
        super(AwsCosting, self).__init__(start, end)

    def _get(self) -> Generator[dict, None, None]:
        """
        Retrieve and format the data as

        {
            'date': date object,
            'cost': float,
            'currency': string
        }

        :todo:  This could be made async
        to process larger streams.

        :returns: Generator Dictionary
        """
        client = boto3.client('ce')
        page_token: Optional[str] = None

        while True:
            if page_token:
                kwargs: dict = {'NextPageToken': page_token}
            else:
                kwargs: dict = {}

            response: dict = client.get_cost_and_usage(
                TimePeriod={
                    'Start': self.start.strftime('%Y-%m-%d'),
                    'End': self.end.strftime('%Y-%m-%d'),
                },
                Granularity='DAILY',
                Metrics=['BlendedCost'],
                Filter={
                    'Tags': {
                        'Key': 'tortuga',
                        'Values': [
                            'cost'
                        ],
                    }
                },
                **kwargs
            )

            for day in response['ResultsByTime']:
                yield {
                    'date': date.fromisoformat(day['TimePeriod']['Start']),
                    'cost': day['Total']['BlendedCost']['Amount'],
                    'currency': day['Total']['BlendedCost']['Unit'],
                }

            page_token = response.get('NextPageToken', None)
            if not page_token:
                break
