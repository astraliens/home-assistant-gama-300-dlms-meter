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
import threading
import datetime
from gurux_common.enums.TraceLevel import TraceLevel

###Python 2 requires this
#pylint: disable=bad-option-value,old-style-class
class _GXSynchronousMediaBase:
    def __init__(self, length=0):
        """Constructor.

        length : receive buffer size.
        """
        #Trace level.
        self.trace = TraceLevel.OFF
        #Occurred exception.
        self.exception = None
        #Received bytes.
        self.__receivedBuffer = bytearray(length)
        #Received event.
        self.__receivedEvent = threading.Event()
        #Synchronous object.
        self.__sync = threading.RLock()
        #Amount of received bytes.
        self.__receivedSize = 0
        #Position where end of packet was last time search.  This is used to
        #improve searching.
        self.__lastPosition = 0

    def resetLastPosition(self):
        """Reset last position."""
        self.__lastPosition = 0

    def resetReceivedSize(self):
        """Reset received size."""
        self.__receivedSize = 0

    def setReceived(self):
        """Set received event."""
        self.__receivedEvent.set()

    def getSync(self):
        """Get synchronous object."""
        return self.__sync

    def getReceivedSize(self):
        """@return Amount of received bytes."""
        return self.__receivedSize

    def getReceivedData(self):
        """@return Get received data."""
        return self.__receivedBuffer[0:self.__receivedSize]

    def appendData(self, data, index, count):
        """Append new data.

        data : data to append.
        index : Index where start.
        count : Count of bytes to add.
        """
        with self.__sync:
            #Allocate new buffer.
            if self.__receivedSize + count > len(self.__receivedBuffer):
                tmp = self.__receivedBuffer
                self.__receivedBuffer = bytearray(2 * len(self.__receivedBuffer))
                self.__receivedBuffer[0:self.__receivedSize] = tmp[0:self.__receivedSize]

            self.__receivedBuffer[self.__receivedSize:self.__receivedSize + count - index] = data[index: count - index]
            self.__receivedSize += count - index

    @classmethod
    def indexOf(cls, data, pattern, index, count):
        """
        Finds the first occurrence of the pattern in the text.
        data : Data where to find.
        pattern : Search pattern.
        index : Byte index to start.
        count : Count of bytes to search.
        Return True if pattern is found.
        """
        failure = _GXSynchronousMediaBase.__computeFailure(pattern)
        j = 0
        if not data or len(data) < index:
            return -1

        for i in range(index, count):
            while j > 0 and pattern[j] != data[i]:
                j = failure[j - 1]
            if pattern[j] == data[i]:
                j = j + 1

            if j == len(pattern):
                return i - len(pattern) + 1
        return -1

    @classmethod
    def __computeFailure(cls, pattern):
        """Computes the failure function using a boot-strapping process, where the
        pattern is matched against itself.

        pattern : Pattern to search.
        Returns Failure pattern.
        """
        failure = bytearray(len(pattern))
        j = 0
        for i in range(1, len(pattern)):
            while j > 0 and pattern[j] != pattern[i]:
                j = failure[j - 1]
            if pattern[j] == pattern[i]:
                j = j + 1

            failure[i] = j
        return failure

    def __findData(self, args):
        """Find data from buffer.
        args : Receive parameters.
        isFound : Is data found in given time.
        Returns : Position where end of packet was found. -1 Is returned if data
        was not found in given time.
        """
        nSize = 0
        foundPosition = -1
        lastBuffSize = 0
        startTime = datetime.datetime.now().time().microsecond
        terminator = None
        nMinSize = args.count
        if nMinSize < nSize:
            nMinSize = nSize

        waitTime = args.waitTime
        self.exception = None
        if waitTime <= 0:
            waitTime = -1
        if args.eop:
            terminator = self.toBytes(args.eop)
            nSize = len(terminator)
        #Wait until reply occurred.
        while foundPosition == -1:
            if waitTime == 0:
                #If we want to read all data.
                if args.allData:
                    foundPosition = self.__receivedSize
                else:
                    foundPosition = -1
                break

            if waitTime != - 1:
                waitTime = args.waitTime - ((datetime.datetime.now().time().microsecond - startTime) / 1000)
                if waitTime < 0:
                    waitTime = 0

            with self.__sync:
                isReceived = not (lastBuffSize == self.__receivedSize or self.__receivedSize < nMinSize)

            # Do not wait if there is data on the buffer...
            if not isReceived:
                if waitTime == - 1:
                    isReceived = self.__receivedEvent.wait()
                elif waitTime != 0:
                    isReceived = self.__receivedEvent.wait(waitTime / 1000)
                self.__receivedEvent.clear()
            if self.exception:
                #pylint: disable=raising-bad-type
                raise self.exception
            #If timeout occurred.
            if not isReceived:
                #If we want to read all data.
                if args.allData and self.__receivedSize != 0:
                    foundPosition = self.__receivedSize
                else:
                    foundPosition = -1
                break

            with self.__sync:
                lastBuffSize = self.__receivedSize
                #Read more data, if not enough.
                if self.__receivedSize < nMinSize:
                    continue

                #If only byte count matters.
                if nSize == 0:
                    foundPosition = args.count
                else:
                    if self.__lastPosition != 0 and self.__lastPosition < self.__receivedSize:
                        index = self.__lastPosition
                    else:
                        index = args.count
                    #If terminator found.
                    if isinstance(args.eop, (list)):
                        raise Exception("Only single byte terminator allowed.")
                    if len(terminator) != 1 and self.__receivedSize - index < len(terminator):
                        index = self.__receivedSize - len(terminator)
                    foundPosition = self.indexOf(self.__receivedBuffer, terminator, index, self.__receivedSize)
                    self.__lastPosition = self.__receivedSize
                    if foundPosition != -1:
                        foundPosition += len(terminator)

        #If terminator is not given read only bytes that are needed.
        if nSize == 0 and foundPosition != -1:
            foundPosition = args.count
        return foundPosition

    def receive(self, args):
        """
        Receive new data synchronously from the media.
        args : Receive parameters.
        Return True if new data is received.
        """
        if args.eop is None and args.count == 0:
            raise Exception("Either Count or Eop must be set.")
        foundPosition = self.__findData(args)
        data = None
        if foundPosition != -1:
            with self.__sync:
                if args.allData:
                    #If all data is copied.
                    foundPosition = self.__receivedSize

                if foundPosition != 0:
                    #Convert bytes to object.
                    data = self.__receivedBuffer[0:foundPosition]
                    #Remove read data.
                    self.__receivedSize -= foundPosition
                    #Received size can go less than zero if we have received
                    #data and we try to read more.
                    if self.__receivedSize < 0:
                        self.__receivedSize = 0
                    if self.__receivedSize != 0:
                        self.__receivedBuffer[0:self.__receivedSize] = self.__receivedBuffer[foundPosition:foundPosition + self.__receivedSize]
            #Reset count after read.
            args.count = 0
            #Append data.
            oldReplySize = 0
            if args.reply is None:
                args.reply = data
            else:
                oldArray = args.reply
                newArray = data
                if newArray:
                    oldReplySize = len(oldArray)
                    len_ = oldReplySize + len(newArray)
                    arr = bytearray(len_)
                    #Copy old values.
                    arr[0:len(oldArray)] = args.reply[0:len(oldArray)]
                    #Copy new values.
                    arr[len(oldArray): len(oldArray) + len(newArray)] = newArray[0:len(newArray)]
                    args.reply = arr
        return foundPosition != -1

    #Convert value to bytes.
    @classmethod
    def toBytes(cls, value):
        if isinstance(value, bytearray):
            pass
        elif isinstance(value, str):
            value = bytearray(value.encode())
        elif isinstance(value, (bytes, list)):
            value = bytearray(value)
        elif isinstance(value, memoryview):
            value = bytearray(value.tobytes())
        elif isinstance(value, int):
            value = bytearray([value])
        else:
            raise ValueError("Invalid data value.")
        return value
