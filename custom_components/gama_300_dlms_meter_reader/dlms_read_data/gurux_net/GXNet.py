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
import socket
import threading
import traceback
from gurux_common.enums import TraceLevel, MediaState, TraceTypes
from gurux_common.IGXMedia import IGXMedia
from gurux_common.MediaStateEventArgs import MediaStateEventArgs
from gurux_common.TraceEventArgs import TraceEventArgs
from gurux_common.PropertyChangedEventArgs import PropertyChangedEventArgs
from .enums.NetworkType import NetworkType
from ._GXSynchronousMediaBase import _GXSynchronousMediaBase
from ._NetReceiveEventArgs import _NetReceiveEventArgs

# pylint: disable=too-many-public-methods, too-many-instance-attributes
class GXNet(IGXMedia):

    def __init__(self, networkType=NetworkType.TCP, name=None, portNo=0):
        """
         Client Constructor.

         networkType :  Used protocol.
         name : Host name.
         portNo : Client port number.
        """
        self.__receiveDelay = 0
        self.__asyncWaitTime = 0
        ###Used protocol.###
        self.__protocol = networkType
        ###Host name.###
        self.__host_name = name
        ###Used port.###
        self.__port = portNo
        ###Is server or client.###
        self.server = False
        ###Created socket.###
        self.__socket = None
        ###Amount of sent bytes.###
        self.__bytesSent = 0
        self.__bytesReceived = 0
        ###Trace level.###
        self.__trace = TraceLevel.OFF
        ###Used end of packet.###
        self.__eop = None
        ###Synchronous data handler.###
        self.__syncBase = _GXSynchronousMediaBase(1024)
        ###Event listeners.
        self.__listeners = []
        self.__netListeners = []
        self.__lock = threading.Lock()
        self.__thread = None
        self.__aThread = None
        #Is IPv6 used.  Default is False (IPv4).
        self.useIPv6 = False

    #pylint: disable=unused-private-member
    def __getTrace(self):
        return self.__trace

    #pylint: disable=unused-private-member
    def __setTrace(self, value):
        self.__trace = value
        self.__syncBase.trace = value

    trace = property(__getTrace, __setTrace)
    """Trace level."""

    def addListener(self, listener):
        self.__listeners.append(listener)

    def removeListener(self, listener):
        self.__listeners.remove(listener)

    def __notifyPropertyChanged(self, info):
        """Notify that property has changed."""
        for it in self.__listeners:
            it.onPropertyChanged(self, PropertyChangedEventArgs(info))

    def __notifyClientConnected(self, e):
        """Notify that client has connected."""
        for it in self.__netListeners:
            it.onClientConnected(self, e)

        if int(self.trace) >= int(TraceLevel.INFO):
            for it in self.__listeners:
                it.onTrace(self, TraceEventArgs(TraceTypes.INFO, "Client connected."))

    def __notifyClientDisconnected(self, e):
        """Notifies clients that client is disconnected."""
        for it in self.__netListeners:
            it.onClientDisconnected(self, e)

        if int(self.__trace) >= int(TraceLevel.INFO):
            for it in self.__listeners:
                it.onTrace(self, TraceEventArgs(TraceTypes.INFO, "Client disconnected."))

    def __notifyError(self, ex):
        """Notify clients from error occurred."""
        for it in self.__listeners:
            it.onError(self, ex)
            if int(self.__trace) >= int(TraceLevel.ERROR):
                it.onTrace(self, TraceEventArgs(TraceTypes.ERROR, ex))

    def __notifyReceived(self, e):
        """Notify clients from new data received."""
        for it in self.__listeners:
            it.onReceived(self, e)

    def __notifyTrace(self, e):
        """Notify clients from trace events."""
        for it in self.__listeners:
            it.onTrace(self, e)

    def send(self, data, receiver=None):
        if not self.__socket:
            raise Exception("Invalid connection.")

        if self.__trace == TraceLevel.VERBOSE:
            self.__notifyTrace(TraceEventArgs(TraceTypes.SENT, data))

        #Reset last position if end of packet is used.
        with self.__syncBase.getSync():
            self.__syncBase.resetLastPosition()

        if not isinstance(data, bytes):
            data = bytes(_GXSynchronousMediaBase.toBytes(data))

        if isinstance(receiver, _NetReceiveEventArgs):
            receiver.socket.sendall(data)
        else:
            self.__socket.sendall(data)
        self.__bytesSent += len(data)

    def __notifyMediaStateChange(self, state):
        ###Notify client from media state change.
        for it in self.__listeners:
            if self.__trace >= TraceLevel.ERROR:
                it.onTrace(self, TraceEventArgs(TraceTypes.INFO, state))
            it.onMediaStateChange(self, MediaStateEventArgs(state))

    #Handle received data.
    def __handleReceivedData(self, buff, s):
        if not buff:
            return
        self.__bytesReceived += len(buff)
        totalCount = 0
        if self.getIsSynchronous():
            arg = None
            with self.__syncBase.getSync():
                self.__syncBase.appendData(buff, 0, len(buff))
                #Search end of packet if it is given.
                if self.eop:
                    tmp = _GXSynchronousMediaBase.toBytes(self.eop)
                    totalCount = _GXSynchronousMediaBase.indexOf(buff, tmp, 0, len(buff))
                if totalCount != -1:
                    if self.trace == TraceLevel.VERBOSE:
                        arg = TraceEventArgs(TraceTypes.RECEIVED, buff, 0, totalCount + 1)
                    self.__syncBase.setReceived()
            if arg:
                self.__notifyTrace(arg)
        else:
            self.__syncBase.resetReceivedSize()
            if self.trace == TraceLevel.VERBOSE:
                self.__notifyTrace(TraceEventArgs(TraceTypes.RECEIVED, buff))
            info = s.getpeername()
            e = _NetReceiveEventArgs(buff, str(info[0]) + ":" + str(info[1]), s)
            self.__notifyReceived(e)

    #pylint: disable=broad-except
    def __listenerThread(self, s):
        while self.__socket and s:
            try:
                data = s.recv(1000)
                if data:
                    #Convert data to bytearray because 2.7 handles bytes as a
                    #string.
                    #This is causing problems with non-ascii chars.
                    data = bytearray(data)
                    self.__handleReceivedData(data, s)
                elif self.server:
                    self.__notifyClientDisconnected(s.getpeername())
                    break
            except ConnectionResetError:
                if not self.server:
                    #Server has close the connection.
                    self.close()
                break
            except Exception:
                if self.__socket:
                    traceback.print_exc()
                else:
                    break

    #pylint: disable=broad-except
    def __acceptThread(self):
        while self.__socket:
            try:
                # accept connections from outside
                (clientsocket, address) = self.__socket.accept()
                self.__notifyClientConnected(address)
                self.__thread = threading.Thread(target=self.__listenerThread, args=(clientsocket,))
                self.__thread.start()
            except Exception:
                if self.__socket:
                    traceback.print_exc()

    def __getInet(self, addr):
        if not addr:
            if self.useIPv6:
                return socket.AF_INET6
            return socket.AF_INET
        if addr.find(":") != -1:
            return socket.AF_INET6
        return socket.AF_INET

    def open(self):
        """Opens the connection. Protocol, Port and HostName must be set, before
        calling the Open method."""
        self.close()
        try:
            with self.__syncBase.getSync():
                self.__syncBase.resetLastPosition()

            self.__notifyMediaStateChange(MediaState.OPENING)
            if self.protocol == NetworkType.TCP or 1==1: # or condition is temporary solution to define why 2 objects with same value and not equal [<NetworkType.TCP: 1>, <NetworkType.TCP: 1>]
                if self.server:
                    self.__socket = socket.socket(self.__getInet(self.__host_name), socket.SOCK_STREAM)
                    if self.__host_name:
                        self.__socket.bind((self.__host_name, self.__port))
                    else:
                        self.__socket.bind((socket.gethostname(), self.__port))
                    self.__socket.listen(5)
                    self.__aThread = threading.Thread(target=self.__acceptThread)
                    self.__aThread.start()
                else:
                    self.__socket = socket.socket(self.__getInet(self.__host_name), socket.SOCK_STREAM)
                    self.__socket.connect((self.__host_name, self.__port))
            else:
                self.__socket = socket.socket(self.__getInet(self.__host_name), socket.SOCK_DGRAM)
                self.__socket.connect((self.__host_name, self.__port))
            self.__notifyMediaStateChange(MediaState.OPEN)
            if not self.server or self.protocol == NetworkType.UDP:
                self.__thread = threading.Thread(target=self.__listenerThread, args=(self.__socket,))
                self.__thread.start()
        except Exception as e:
            self.close()
            raise e

    def close(self):
        if self.__socket:
            self.__notifyMediaStateChange(MediaState.CLOSING)
            try:
                #This will fail if connection is closed on server side.
                if self.__socket:
                    tmp = self.__socket
                    self.__socket = None
                    if not self.server:
                        tmp.shutdown(socket.SHUT_RDWR)
                    tmp.close()
            except Exception:
                pass
            try:
                if self.__thread:
                    self.__thread.join()
                    self.__thread = None
            except Exception:
                pass
            try:
                if self.__aThread:
                    self.__aThread.join()
                    self.__aThread = None
            except Exception:
                pass
            self.__notifyMediaStateChange(MediaState.CLOSED)
            self.__bytesSent = 0
            self.__syncBase.resetReceivedSize()

    def isOpen(self):
        return self.__socket is not None

    def __getProtocol(self):
        return self.__protocol
    def __setProtocol(self, value):
        if self.__protocol != value:
            self.__protocol = value
            self.__notifyPropertyChanged("protocol")

    protocol = property(__getProtocol, __setProtocol)
    """Protocol."""

    def __getHostName(self):
        return self.__host_name

    def __setHostName(self, value):
        if self.__host_name != value:
            self.__host_name = value
            self.__notifyPropertyChanged("hostName")

    hostName = property(__getHostName, __setHostName)
    """Host name."""

    def __getPort(self):
        return self.__port

    def __setPort(self, value):
        if self.__port != value:
            self.__port = value
            self.__notifyPropertyChanged("port")


    port = property(__getPort, __setPort)
    """Port number."""

    def receive(self, args):
        return self.__syncBase.receive(args)

    def getBytesSent(self):
        """Sent byte count."""
        return self.__bytesSent

    def getBytesReceived(self):
        """Received byte count."""
        return self.__bytesReceived

    def resetByteCounters(self):
        """Resets BytesReceived and BytesSent counters."""
        self.__bytesSent = 0
        self.__bytesReceived = 0

    def getSettings(self):
        """Media settings as a XML string."""
        sb = ""
        nl = "\r\n"
        if self.__host_name:
            sb += "<IP>"
            sb += self.__host_name
            sb += "</IP>"
            sb += nl
        if self.__port != 0:
            sb += "<Port>"
            sb += str(self.__port)
            sb += "</Port>"
            sb += nl

        if self.__protocol != NetworkType.TCP:
            sb += "<Protocol>"
            sb += str(int(self.__protocol))
            sb += "</Protocol>"
            sb += nl
        return sb

    def setSettings(self, value):
        #Reset to default values.
        self.__host_name = ""
        self.__port = 0
        self.__protocol = NetworkType.TCP


    def copy(self, target):
        self.__port = target.port
        self.__host_name = target.hostName
        self.__protocol = target.protocol

    def getName(self):
        tmp = self.__host_name + " " + self.__port
        if self.__protocol == NetworkType.UDP:
            tmp += "UDP"
        else:
            tmp += "TCP/IP"
        return tmp

    def getMediaType(self):
        return "Net"

    def getSynchronous(self):
        return self.__lock

    #pylint: disable=no-member
    def getIsSynchronous(self):
        return self.__lock.locked()

    def resetSynchronousBuffer(self):
        with self.__syncBase.getSync():
            self.__syncBase.resetReceivedSize()

    def validate(self):
        if self.__port == 0:
            raise Exception("Invalid port name.")
        if not self.hostName:
            raise Exception("Invalid host name.")

    def __getEop(self):
        return self.__eop

    def __setEop(self, value):
        self.__eop = value

    eop = property(__getEop, __setEop)

    def getReceiveDelay(self):
        return self.__receiveDelay

    def setReceiveDelay(self, value):
        self.__receiveDelay = value

    def getAsyncWaitTime(self):
        return self.__asyncWaitTime

    def setAsyncWaitTime(self, value):
        self.__asyncWaitTime = value

    def __str__(self):
        if self.__protocol == NetworkType.TCP:
            tmp = "TCP "
        else:
            tmp = "UDP "
        if self.server:
            tmp = tmp + "Server "
        if self.__host_name:
            tmp = tmp + self.__host_name
        elif self.server:
            tmp = tmp + socket.gethostname()
        return tmp + ":" + str(self.__port)
