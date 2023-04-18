import os
import sys
import traceback
import json
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
    def __init__(self,host,port,serial):
        self.settings=GXSettings(host,port,serial)
        self.reader=GXDLMSReader(self.settings.client, self.settings.media, self.settings.trace, self.settings.invocationCounter)
        self.connected=False
        self.connecting=False
        self.host=host
        self.port=port
        self.serial=serial

    def connect(self):
        self.connecting=True
        self.settings.media.open()
        self.reader.initializeConnection()
        self.reader.getAssociationView()
        self.connected=True # need to detect later if there were any errors during connection and define connected status based on this result

    def disconnect(self):
        self.connecting=False
        self.connected=False
        self.reader.disconnect()

    def reconnect(self):
        if(self.connecting==False):
            self.disconnect()
            self.connect()

    def online(self):
        return self.connected

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

    def ReadItem(self,item,attr):
        if(self.online()==False):
           self.connect()
        obj = self.settings.client.objects.findByLN(ObjectType.NONE, item)
        if obj is None:
            return ''
        return self.reader.read(obj, attr)

    def ReadAllDataSYNC(self):
        total_list=[]
        for item in self.GetDataList():
            res=self.ReadItem(item['meter_param'],item['meter_attr'])
            if 'multiplier' in item:
                res=res * item['multiplier']

                multiplier_type=type(item['multiplier'])
                if(multiplier_type==float):
                    precision=self.MultiplierToPrecision(item['multiplier'])
                    res=round(res, precision)

            item['value']=res
            if 'unit' not in item:
                item['unit']=''

            total_list.append(item)
        return total_list

    async def ReadAllData(self):
        total_list=[]
        for item in self.GetDataList():
            res=self.ReadItem(item['meter_param'],item['meter_attr'])
            if 'multiplier' in item:
                res=res * item['multiplier']

                multiplier_type=type(item['multiplier'])
                if(multiplier_type==float):
                    precision=self.MultiplierToPrecision(item['multiplier'])
                    res=round(res, precision)

            item['value']=res
            if 'unit' not in item:
                item['unit']=''

            total_list.append(item)
        return total_list
    
    def ReadSingleData(self, param):
        for item in self.GetDataList():
            if (item['meter_param']==param):
                res=self.ReadItem(item['meter_param'],item['meter_attr'])
                if 'multiplier' in item:
                    res=res * item['multiplier']

                    multiplier_type=type(item['multiplier'])
                    if(multiplier_type==float):
                        precision=self.MultiplierToPrecision(item['multiplier'])
                        res=round(res, precision)

                item['value']=res
                if 'unit' not in item:
                    item['unit']=''
            return item


    async def ReadAllConfig(self):
        total_list=[]
        for item in self.GetMeterConfigList():
            res=self.ReadItem(item['meter_param'],item['meter_attr'])
            item['value']=res
            total_list.append(item)
        return total_list

    async def ReadSingleConfig(self, param):
        for item in self.GetMeterConfigList():
            if(item['meter_param']==param):
                res=self.ReadItem(item['meter_param'],item['meter_attr'])
                item['value']=res
            return item

    def GetDataList(self):
        basepath = path.dirname(__file__)
        filepath = basepath + "/meter_data.json"
        meter_data_file = open(filepath)
        data = json.load(meter_data_file)
        meter_data_file.close()
        return data

    def GetMeterConfigList(self):
        basepath = path.dirname(__file__)
        filepath = basepath + "/meter_param.json"
        meter_data_file = open(filepath)
        data = json.load(meter_data_file)
        meter_data_file.close()
        return data

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