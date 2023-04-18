# Home Assistant ELGAMA GAMA300 DLMS over TCPIP
Home Assistant Integration for reading data from ELGAMA GAMA300 electricity meter (GAMA100 not tested, but possibly supported too) via RS485-TCP Gateway

## Features

- Get most of live values from meter
- Add energy sensors for integration with energy usage
- Tracks daily / total energy consumption

## Notes

This code was written for couple of days without any skills in Python and HA architecture. That is second time I've used Python, so anyone is welcome to make this code better.

## Connecting meter to gateway and HA

First your meter must support RS485 interface (check your meter manual or model number to ensure your meter support it, but also you can try to connect optical reader to gateway). To connect meter to HA you need any RS485->TCP gateway (I've used HI-FLYING HF5142B, coz prefer wires, but you can use any other or try to connect it with esp32 / 8266 with RS485 converter bridging it to TCP socket).
On gateway side you should configure TCP server to forward data from RS485 port, it should be tcp server without authorization, you can choose any port to listen.

#### RS485 params:
- Baud rate: 9600
- Data bit: 8
- Stop bit: 1
- Parity: None

![HF5142B_connection](https://raw.githubusercontent.com/astraliens/home-assistant-gama-300-dlms-meter/main/images/HF5142B_connection.jpg)
![HF5142B_TCP_Server](https://raw.githubusercontent.com/astraliens/home-assistant-gama-300-dlms-meter/main/images/HF5142B_TCP_Server.jpg)

After connecting meter you need to add `home-assistant-gama-300-dlms-meter` integration using HACS to your HA. In you HA go to *Main Menu -> HACS -> Integrations*, in top right corner press 3 dots and click to "Custom Repositories". Add repository `https://github.com/astraliens/home-assistant-gama-300-dlms-meter` and category `Integration`. After this step close modal add repository window and press "Explore & Download Repositories" blue button at the bottom right corner of screen and search for `Gama 300 DLMS Meter` integration. Press on it and in right bottom corner of screen press "Download" button. 
After this you can simply add it like regular integration, specifiying IP and port of gateway and your meter serial number (you can find it on meter itself). In several seconds integration get data from meter, create all found sensors and will update them constantly.

Pinout of meter shown on photo:

![gama_300_rs485_pinout](https://raw.githubusercontent.com/astraliens/home-assistant-gama-300-dlms-meter/main/images/gama_300_rs485_pinout.jpg)


## Energy consumption monitoring

You can add `Sum Li Active power+ (QI+QIV) Time integral 1 Rate 0` sensor to your energy consumption monitoring to calculate your overall spents

## DLMS Protocol

Many thanks to <a href="https://www.gurux.fi/Gurux.DLMS">Gurux</a> for Python library implementation which used in this integration to retrieve data from meter

## Donations

You can say thanks by donating for buying pizza at:

<a href="https://www.buymeacoffee.com/astraliens" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/default-orange.png" alt="Buy Me A Pizza" height="41" width="174"></a>
