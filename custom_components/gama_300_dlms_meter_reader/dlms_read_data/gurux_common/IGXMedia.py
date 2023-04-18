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
import abc
from .GXCommon import GXCommon

ABC = abc.ABCMeta('ABC', (object,), {'__slots__': ()})
#pylint: disable=syntax-error
if GXCommon.getVersion() >= (2, 7):
    class IGXMedia(ABC):
        #pylint: disable=too-many-public-methods
        """Common interface for all Media components.
        Using this interface GXCommunication library enables communication with\
        different medias."""

        @abc.abstractmethod
        def addListener(self, listener):
            """Start to listen media events."""

        @abc.abstractmethod
        def removeListener(self, listener):
            """Stop to listen media events."""

        @abc.abstractmethod
        def copy(self, target):
            """ Copies the content of the media to target media.
            target : Target media."""

        @abc.abstractmethod
        def getName(self):
            """ Returns name of the media. Media name is used to identify media
            connection, so two different media connection can not return same media
            name.

            Returns Media name."""

        @abc.abstractproperty
        def trace(self):
            """Trace level of the IGXMedia."""

        @abc.abstractmethod
        def open(self):
            """Opens the media."""

        @abc.abstractmethod
        def isOpen(self):
            """Checks if the connection is established.
            Returns True, if the connection is established."""

        @abc.abstractmethod
        def close(self):
            """Closes the active connection."""

        @abc.abstractmethod
        def send(self, data, receiver):
            """Sends data asynchronously. No reply from the receiver, whether or not the
            operation was successful, is expected.

            data : Data to send to the device.
            receiver : Media depend information of the receiver (optional)."""

        @abc.abstractmethod
        def getMediaType(self):
            """Returns media type as a string."""

        @abc.abstractmethod
        def getSettings(self):
            """Get media settings as a XML string."""

        @abc.abstractmethod
        def setSettings(self, value):
            """Set media settings as a XML string."""

        @abc.abstractmethod
        def getSynchronous(self):
            """Locking this property makes the connection synchronized and stops sending
            OnReceived events."""

        @abc.abstractmethod
        def getIsSynchronous(self):
            """Checks if the connection is in synchronous mode."""

        @abc.abstractmethod
        def receive(self, args):
            """Waits for more reply data After SendSync if whole packet is not received yet."""

        @abc.abstractmethod
        def resetSynchronousBuffer(self):
            """Resets synchronous buffer."""

        @abc.abstractmethod
        def getBytesSent(self):
            """Sent byte count."""

        @abc.abstractmethod
        def getBytesReceived(self):
            """Received byte count."""

        @abc.abstractmethod
        def resetByteCounters(self):
            """Resets BytesReceived and BytesSent counters."""

        @abc.abstractmethod
        def validate(self):
            """Validate Media settings for connection open. Returns table of media
            properties that must be set before media is valid to open."""

        @abc.abstractproperty
        def eop(self):
            """End of the packet."""
else:
    class IGXMedia(ABC):
        #pylint: disable=too-many-public-methods
        """Common interface for all Media components.
        Using this interface GXCommunication library enables communication with\
        different medias."""

        @abc.abstractmethod
        def addListener(self, listener):
            """Start to listen media events."""

        @abc.abstractmethod
        def removeListener(self, listener):
            """Stop to listen media events."""

        @abc.abstractmethod
        def copy(self, target):
            """ Copies the content of the media to target media.
            target : Target media."""

        @abc.abstractmethod
        def getName(self):
            """ Returns name of the media. Media name is used to identify media
            connection, so two different media connection can not return same media
            name.

            Returns Media name."""

        @abc.abstractproperty
        def trace(self):
            """Trace level of the IGXMedia."""

        @abc.abstractmethod
        def open(self):
            """Opens the media."""

        @abc.abstractmethod
        def isOpen(self):
            """Checks if the connection is established.
            Returns True, if the connection is established."""

        @abc.abstractmethod
        def close(self):
            """Closes the active connection."""

        @abc.abstractmethod
        def send(self, data, receiver):
            """Sends data asynchronously. No reply from the receiver, whether or not the
            operation was successful, is expected.

            data : Data to send to the device.
            receiver : Media depend information of the receiver (optional)."""

        @abc.abstractmethod
        def getMediaType(self):
            """Returns media type as a string."""

        @abc.abstractmethod
        def getSettings(self):
            """Get media settings as a XML string."""

        @abc.abstractmethod
        def setSettings(self, value):
            """Set media settings as a XML string."""

        @abc.abstractmethod
        def getSynchronous(self):
            """Locking this property makes the connection synchronized and stops sending
            OnReceived events."""

        @abc.abstractmethod
        def getIsSynchronous(self):
            """Checks if the connection is in synchronous mode."""

        @abc.abstractmethod
        def receive(self, args):
            """Waits for more reply data After SendSync if whole packet is not received yet."""

        @abc.abstractmethod
        def resetSynchronousBuffer(self):
            """Resets synchronous buffer."""

        @abc.abstractmethod
        def getBytesSent(self):
            """Sent byte count."""

        @abc.abstractmethod
        def getBytesReceived(self):
            """Received byte count."""

        @abc.abstractmethod
        def resetByteCounters(self):
            """Resets BytesReceived and BytesSent counters."""

        @abc.abstractmethod
        def validate(self):
            """Validate Media settings for connection open. Returns table of media
            properties that must be set before media is valid to open."""

        @abc.abstractproperty
        def eop(self):
            """End of the packet."""
