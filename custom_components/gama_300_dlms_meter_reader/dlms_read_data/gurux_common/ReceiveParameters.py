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

###Python 2 requires this ot property is not working.
#pylint: disable=bad-option-value, useless-object-inheritance
class ReceiveParameters(object):
    """ReceiveParameters class is used when data is read synchronously."""
    #pylint: disable=too-few-public-methods

    def __init__(self):
        """Constructor."""
        self.__waitTime = -1
        ###How long reply message is waited.
        self.allData = False
        ###Is all data read when End of packet is found.
        self.reply = None
        ###Received data.
        self.peek = False
        ###If true, returns the bytes from the buffer without removing.
        self.__eop = None
        ###End of packet waited for.
        self.__count = 0
        ###Minimum count of bytes waited for.


    def __getEop(self):
        return self.__eop

    def __setEop(self, value):
        self.__eop = value

    eop = property(__getEop, __setEop)
    """The end of packet (EOP) waited for."""

    def __getCount(self):
        return self.__count

    def __setCount(self, value):
        if value < 0:
            raise ValueError("Count")
        self.__count = value

    count = property(__getCount, __setCount)
    """The number of reply data bytes to be read."""

    def __getWaitTime(self):
        return self.__waitTime

    def __setWaitTime(self, value):
        self.__waitTime = value

    waitTime = property(__getWaitTime, __setWaitTime)
    """Maximum time, in milliseconds, to wait for reply data. WaitTime -1
    (Default value) indicates infinite wait time."""
