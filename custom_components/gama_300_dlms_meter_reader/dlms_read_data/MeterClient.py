import os
import sys
import traceback
import json
import threading
#from gurux_serial import GXSerial
from os import path

import logging
_LOGGER = logging.getLogger(__name__)

sys.path.append(path.dirname(__file__)) # add current path to syspath so we can import dlms library and all imports inside dlms library will work

from gurux_net import GXNet
from gurux_dlms.enums import ObjectType
from gurux_dlms.objects.GXDLMSObjectCollection import GXDLMSObjectCollection
#from GXSettings import GXSettings
from GXDLMSReader import GXDLMSReader
from gurux_dlms.GXDLMSClient import GXDLMSClient
from gurux_common.GXCommon import GXCommon
from gurux_dlms.enums.DataType import DataType
import locale
from gurux_dlms.GXDateTime import GXDateTime
from gurux_dlms.internal._GXCommon import _GXCommon
from gurux_dlms import GXDLMSException, GXDLMSExceptionResponse, GXDLMSConfirmedServiceError, GXDLMSTranslator
from gurux_dlms import GXByteBuffer, GXDLMSTranslatorMessage, GXReplyData
from gurux_dlms.enums import RequestTypes, Security, InterfaceType
from gurux_dlms.secure.GXDLMSSecureClient import GXDLMSSecureClient


#from gurux_dlms.enums import InterfaceType, Authentication, Security, Standard
#from gurux_dlms import GXDLMSClient
#from gurux_dlms.secure import GXDLMSSecureClient
#from gurux_dlms.GXByteBuffer import GXByteBuffer
#from gurux_dlms.objects import GXDLMSObject
from .gurux_common.enums import TraceLevel
#from gurux_common.io import Parity, StopBits, BaudRate
from .gurux_net.enums import NetworkType
#from gurux_net import GXNet
#from gurux_serial.GXSerial import GXSerial

import socket

class GXSettings:
    #
    # Constructor.
    #
    def __init__(self, host, port, serial):
        self.media = None
        self.trace = TraceLevel.INFO
        self.invocationCounter = None
        self.client = GXDLMSSecureClient(True)
        #  Objects to read.
        self.readObjects = []
        self.outputFile = None

        self.media = GXNet(NetworkType.TCP, host, 0)
        self.media.port = int(port)
        self.client.useLogicalNameReferencing = False
        self.client.serverAddress = GXDLMSClient.getServerAddressFromSerialNumber(int(serial))
        self.client.gbtWindowSize = int(1)
        self.client.hdlcSettings.maxInfoRX = self.client.hdlcSettings.maxInfoTX = int(128)
        #self.trace = TraceLevel.VERBOSE
        self.trace = 0

class MeterClient:
    """Blocking DLMS client. Call from an executor thread, not the event loop.

    Uses RLock so reconnect()/read_item() can call connect() while already
    holding the lock without deadlocking.
    """

    def __init__(self,host,port,serial):
        self.settings=GXSettings(host,port,serial)
        self.reader=GXDLMSReader(self.settings.client, self.settings.media, self.settings.trace, self.settings.invocationCounter)
        self.connected=False
        self.connecting=False
        self.host=host
        self.port=port
        self.serial=serial
        self._lock=threading.RLock()
        self._data_list_cache=None
        self._config_list_cache=None

    def connect(self):
        """Open the transport and DLMS association. Closes the socket on failure."""
        with self._lock:
            self.connecting=True
            try:
                self.settings.media.open()
                self.reader.initializeConnection()
                self.reader.getAssociationView()
                self.connected=True # need to detect later if there were any errors during connection and define connected status based on this result
            except Exception:
                self.connected=False
                self._close_transport()
                raise
            finally:
                self.connecting=False

    def _close_transport(self):
        """Close media if open; never raises (safe from connect/disconnect)."""
        try:
            media=self.settings.media
            if media is not None and media.isOpen():
                media.close()
        except Exception:
            _LOGGER.debug("Failed to close meter transport", exc_info=True)

    def disconnect(self):
        """Close association and transport. Safe if never connected."""
        with self._lock:
            try:
                try:
                    self.reader.disconnect()
                except Exception:
                    _LOGGER.debug("DLMS disconnect request failed, closing transport anyway", exc_info=True)
                self._close_transport()
            finally:
                self.connected=False
                self.connecting=False

    def reconnect(self):
        """Teardown and connect again. Errors from connect() propagate."""
        with self._lock:
            self.disconnect()
            self.connect()

    def is_connected(self):
        """Last known session flag (does not probe the socket)."""
        return self.connected

    def online(self):
        """Alias for is_connected()."""
        return self.is_connected()

    def GetMeterValue(self,val):
        if isinstance(val, (bytes, bytearray)):
            val = GXByteBuffer(val)
        elif isinstance(val, list):
            str_ = ""
            for tmp in val:
                if str_:
                    str_ += ", "
                if isinstance(tmp, bytes):
                    str_ += GXByteBuffer.hex(tmp)
                else:
                    str_ += str(tmp)
            val = str_
        return val

    def read_item(self, obis, attr):
        """Read one OBIS attribute; connects first if needed."""
        with self._lock:
            if not self.is_connected():
                self.connect()
            obj = self.settings.client.objects.findByLN(ObjectType.NONE, obis)
            if obj is None:
                return ''
            return self.reader.read(obj, attr)

    def ReadItem(self,item,attr):
        return self.read_item(item, attr)

    def list_available_obis(self):
        """Logical names present in the association view; no I/O (already fetched by connect())."""
        with self._lock:
            available = set()
            for obj in self.settings.client.objects:
                try:
                    name = obj.logicalName
                    if not isinstance(name, str):
                        continue
                    name = name.strip()
                    if name:
                        available.add(name)
                except Exception:
                    continue
            return available

    def filter_known(self, items):
        """Drop items whose OBIS is absent from the association view.

        Trusted only when the view is non-empty: an empty or unreadable view
        falls back to the full list so a connection hiccup never hides entities.
        """
        try:
            available = self.list_available_obis()
        except Exception:
            return items
        if not available:
            return items
        return [item for item in items if item['meter_param'] in available]

    def _apply_multiplier(self, item, res):
        if 'multiplier' in item and isinstance(res, (int, float)):
            res = res * item['multiplier']
            if type(item['multiplier']) == float:
                precision = self.MultiplierToPrecision(item['multiplier'])
                res = round(res, precision)
        return res

    def read_all_data(self):
        """Read all data OBIS values from the parameter list."""
        with self._lock:
            total_list=[]
            for item in self.filter_known(self.GetDataList()):
                res=self.read_item(item['meter_param'],item['meter_attr'])
                res=self._apply_multiplier(item, res)

                item['value']=res
                if 'unit' not in item:
                    item['unit']=''

                total_list.append(item)
            return total_list

    def ReadAllDataSYNC(self):
        return self.read_all_data()

    async def ReadAllData(self):
        return self.read_all_data()

    def read_single_data(self, param):
        """Read one data item by meter_param, or None if unknown."""
        with self._lock:
            for item in self.GetDataList():
                if item['meter_param']==param:
                    res=self.read_item(item['meter_param'],item['meter_attr'])
                    res=self._apply_multiplier(item, res)

                    item['value']=res
                    if 'unit' not in item:
                        item['unit']=''
                    return item
            return None

    def ReadSingleData(self, param):
        return self.read_single_data(param)

    def read_all_config(self):
        """Read all diagnostic/config OBIS values from the parameter list."""
        with self._lock:
            total_list=[]
            for item in self.filter_known(self.GetMeterConfigList()):
                res=self.read_item(item['meter_param'],item['meter_attr'])
                item['value']=res
                total_list.append(item)
            return total_list

    async def ReadAllConfig(self):
        return self.read_all_config()

    def read_single_config(self, param):
        """Read one config item by meter_param, or None if unknown."""
        with self._lock:
            for item in self.GetMeterConfigList():
                if item['meter_param']==param:
                    res=self.read_item(item['meter_param'],item['meter_attr'])
                    item['value']=res
                    return item
            return None

    async def ReadSingleConfig(self, param):
        return self.read_single_config(param)

    def _load_json_file(self, filename):
        basepath = path.dirname(__file__)
        filepath = basepath + "/" + filename
        meter_data_file = open(filepath)
        try:
            return json.load(meter_data_file)
        finally:
            meter_data_file.close()

    def GetDataList(self):
        # Copies: callers mutate item['value']/['unit'] in place.
        if self._data_list_cache is None:
            self._data_list_cache = self._load_json_file("meter_data.json")
        return [dict(item) for item in self._data_list_cache]

    def GetMeterConfigList(self):
        # Copies: callers mutate item['value'] in place.
        if self._config_list_cache is None:
            self._config_list_cache = self._load_json_file("meter_param.json")
        return [dict(item) for item in self._config_list_cache]

    def MultiplierToPrecision (self,val):
        precision = 0
        while val % 1 != 0:
            val *= 10
            precision += 1
        return precision

    def get_model(self):
        #model_data=self.ReadSingleConfig('1.0.96.1.1.255')
        #return model_data["value"]
        return "Meter Model"

    def get_firmware_version(self):
        return "Meter FW VERSION"

    def get_manufacturer(self):
        return "DLMS Meter"
