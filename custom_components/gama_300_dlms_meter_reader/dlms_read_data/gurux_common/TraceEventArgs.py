#
#  --------------------------------------------------------------------------
#   Gurux Ltd
#
#
#
#  Filename: $HeadURL$
#
#  Version: $Revision$,
#                $Date$
#                $Author$
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
import datetime
from .GXCommon import GXCommon

###Python 2 requires this ot property is not working.
#pylint: disable=bad-option-value, useless-object-inheritance
class TraceEventArgs(object):
    #pylint: disable=too-few-public-methods
    """Argument class for IGXMedia connection and disconnection events."""

    def __init__(self, traceType, data, index=0, length=None):
        """
        Constructor.

        type : Trace type.
        data : Send or received data.
        index : Index where data copy is started.
        length : How many bytes are included to data.
        """

        ###Time stamp when data is send or received.
        self.timestamp = datetime.datetime.now()
        ###Trace type.
        self.type = traceType
        if isinstance(data, (bytearray, bytes)):
            if length is None or index != 0:
                length = len(data) - index
            ###Send or received data.
            self.__data = data[index:length]
        else:
            self.__data = data

    def __getData(self):
        return self.__data

    def __setData(self, value):
        self.__data = value

    data = property(__getData, __setData)
    """Send or received data."""

    def dataToString(self):
        """Convert data to string."""
        if not self.data:
            return ""
        if isinstance(self.data, (bytearray, bytes)):
            return GXCommon.toHex(self.data)
        return str(self.data)

    def __str__(self):
        return self.timestamp.strftime("%H:%M:%S") + "\t" + str(self.type) + "\t" + self.dataToString()
