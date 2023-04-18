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
#pylint: disable=broad-except,no-name-in-module
try:
    from enum import IntEnum
    __base = IntEnum
except Exception:
    __base = object

class BaudRate(__base):
    """Defines a list of commonly supported serial communication rates (baud rates)."""
    BAUD_RATE_38400 = 38400
    """38,400 baud."""
    BAUD_RATE_19200 = 19200
    """19,200 baud."""
    BAUD_RATE_9600 = 9600
    """9,600 baud."""
    BAUD_RATE_4800 = 4800
    """4,800 baud."""
    BAUD_RATE_2400 = 2400
    """2,400 baud."""
    BAUD_RATE_1800 = 1800
    """1,800 baud."""
    BAUD_RATE_600 = 600
    """600 baud."""
    BAUD_RATE_300 = 300
    """300 baud."""
