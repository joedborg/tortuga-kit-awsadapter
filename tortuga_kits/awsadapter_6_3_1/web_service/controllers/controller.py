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
import cherrypy

from tortuga.web_service.controllers.tortugaController import TortugaController
from tortuga_kits.aws.costing import AwsCosting

class AwsWsController(TortugaController):
    """
    """
    actions = [
        {
            'name': 'get_costing',
            'path': '/v1/aws/costing/',
            'action': 'get',
            'method': ['GET'],
        },
    ]

    @cherrypy.tools.json_out()
    @cherrypy.tools.json_in()
    @authentication_required()
    def get(self):
        try:
            response = AwsCosting(
                start='',
                end=''
            ).json()
        except Exception as :
            response = self.errorResponse(str(ex))

        return self.formatResponse(response)