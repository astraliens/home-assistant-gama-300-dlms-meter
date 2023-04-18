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
    from enum import Flag
    __base = Flag

class TraceTypes(__base):
    #pylint: disable=too-few-public-methods
    """Trace Type enumerates where trace is sent."""
    SENT = 0x1
    ###Data is sent.
    RECEIVED = 0x2
    ###Data is received.
    ERROR = 0x4
    ###Error has occurred.
    WARNING = 0x8
    ###Warning.
    INFO = 0x10
    ###Info. Example Media states are notified as info.
