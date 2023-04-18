#
#  --------------------------------------------------------------------------
#   Gurux Ltd
#
#
#
#  Filename: $HeadURL$
#
#  Version: $Revision$,
#                   $Date$
#                   $Author$
#
#  Copyright (c) Gurux Ltd
#
# ---------------------------------------------------------------------------
#
#   DESCRIPTION
#
#  This file is a part of Gurux Device Framework.
#
#  Gurux Device Framework is Open Source software; you can redistribute it
#  and/or modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; version 2 of the License.
#  Gurux Device Framework is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#  See the GNU General Public License for more details.
#
#  More information of Gurux products: http://www.gurux.org
#
#  This code is licensed under the GNU General Public License v2.
#  Full text may be retrieved at http://www.gnu.org/licenses/gpl-2.0.txt
# ---------------------------------------------------------------------------
from ..GXCommon import GXCommon

#pylint: disable=no-name-in-module
if GXCommon.getVersion() < (3, 6):
    __base = object
else:
    from enum import IntFlag
    __base = IntFlag

class TraceLevel(__base):
    ###Specifies trace levels.###
    #pylint: disable=too-few-public-methods

    OFF = 0x0
    ###Output no tracing and debugging messages.###

    ERROR = 0x1
    ###Output error-handling messages.###

    WARNING = 0x2
    ###Output warnings and error-handling messages.###

    INFO = 0x4
    ###Output informational messages, warnings, and error-handling messages.###

    VERBOSE = 0x8
    ###Output all debugging and tracing messages.###
