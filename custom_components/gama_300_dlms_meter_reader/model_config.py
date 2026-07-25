"""Decoder for the GAMA 300 order-code string (e.g. 230.F47.B2.P4.C311.A3.L1).

Field layout confirmed only for the G3B family (docs_info/G3B_RU_2_4_smart.pdf,
section 5). Other models are left undecoded rather than guessed.
"""

_SUPPORTED_MODEL_PREFIX = "G3B"

_CURRENT = {"1": "1 A", "2": "5 A", "3": "10 A", "4": "2 A"}
_VOLTAGE = {
    "1": "3x57.7/100, 3x63.5/110, 3x69.2/120 V (or 3x100/110/120 V)",
    "2": "3x120/208, 3x127/220, 3x220, 3x230 V",
    "3": "3x220/380, 3x230/400, 3x240/415 V",
    "4": "3x57.7/100...230/400 V",
}
_FREQUENCY = {"0": "50 Hz", "1": "60 Hz"}

_ENERGY_MEASUREMENT = {
    "1": "Active energy, one direction (|A|)",
    "2": "Active energy, two directions (+A, -A)",
    "3": "Active one direction, reactive two directions (|A|, +R, -R)",
    "4": "Active two directions, reactive two directions (+A, -A, +R, -R)",
    "5": "Active two directions, reactive by quadrant (+A, -A, R1-R4)",
    "6": "Active |A|/+A/-A, reactive two directions (+R, -R)",
    "7": "Active two directions, reactive two directions and by quadrant",
}
_PROGRAMMABLE_FUNCTIONS = {
    "0": "None",
    "7": "Instantaneous values per phase, load profiles",
}
_BUTTON_FUNCTION = {
    "1": "End of billing period",
    "2": "Communication unlock for parametrization",
    "4": "End of billing period + communication unlock",
}
_BACKUP_POWER = {
    "1": "Supercapacitor",
    "2": "Non-replaceable battery",
    "3": "Replaceable battery",
    "4": "Replaceable battery + supercapacitor",
    "5": "Non-replaceable battery + supercapacitor",
}
_COMM_DEVICE = {
    "0": "None",
    "1": "Optical",
    "2": "Optical + 20 mA current loop",
    "3": "Optical + RS485",
}
_S0_OUTPUTS = {
    "0": "None",
    "1": "One S0 output",
    "3": "Two S0 outputs",
    "4": "Three S0 outputs",
    "5": "One S0 output + one pulse input",
    "6": "Three S0 outputs + one pulse input",
    "7": "Four S0 outputs",
}
_RELAY_OUTPUTS = {"0": "None", "1": "One relay output", "2": "Two relay outputs", "3": "Three relay outputs"}
_ADDITIONAL_COMM = {"1": "20 mA current loop", "2": "RS232", "3": "RS485", "6": "Wired M-Bus master"}
_DISCONNECT_RELAY = {"1": "Present"}
_BACKLIGHT = {"1": "With backlight"}
_EXTERNAL_POWER = {"1": "Present"}
_PLC_MODEM = {"1": "Yitran", "2": "PRIME"}


def _rating(token):
    if len(token) != 3 or not token.isdigit():
        return {}
    current, voltage, frequency = token[0], token[1], token[2]
    attrs = {}
    if current in _CURRENT:
        attrs["Current rating"] = _CURRENT[current]
    if voltage in _VOLTAGE:
        attrs["Voltage rating"] = _VOLTAGE[voltage]
    if frequency in _FREQUENCY:
        attrs["Frequency"] = _FREQUENCY[frequency]
    return attrs


def _energy_functions(digits):
    # "F47" is digits 4 and 7 read separately, not the single code "F7".
    if len(digits) != 2 or not digits.isdigit():
        return {}
    attrs = {}
    if digits[0] in _ENERGY_MEASUREMENT:
        attrs["Energy measurement"] = _ENERGY_MEASUREMENT[digits[0]]
    if digits[1] in _PROGRAMMABLE_FUNCTIONS:
        attrs["Programmable functions"] = _PROGRAMMABLE_FUNCTIONS[digits[1]]
    return attrs


def _comm_ports(digits):
    if len(digits) != 3 or not digits.isdigit():
        return {}
    attrs = {}
    if digits[0] in _COMM_DEVICE:
        attrs["Communication device"] = _COMM_DEVICE[digits[0]]
    if digits[1] in _S0_OUTPUTS:
        attrs["S0 outputs"] = _S0_OUTPUTS[digits[1]]
    if digits[2] in _RELAY_OUTPUTS:
        attrs["Relay outputs"] = _RELAY_OUTPUTS[digits[2]]
    return attrs


def _single_code(table, key, digits):
    if digits in table:
        return {key: table[digits]}
    return {}


_SEGMENT_DECODERS = {
    "F": _energy_functions,
    "B": lambda digits: _single_code(_BUTTON_FUNCTION, "Sealed button function", digits),
    "P": lambda digits: _single_code(_BACKUP_POWER, "Backup power source", digits),
    "C": _comm_ports,
    "A": lambda digits: _single_code(_ADDITIONAL_COMM, "Additional communication device", digits),
    "R": lambda digits: _single_code(_DISCONNECT_RELAY, "Internal disconnect relay", digits),
    "L": lambda digits: _single_code(_BACKLIGHT, "LCD backlight", digits),
    "M": lambda digits: _single_code(_EXTERNAL_POWER, "External power connector", digits),
    "H": lambda digits: _single_code(_PLC_MODEM, "Internal PLC modem", digits),
}


def decode_model_config(model, config):
    """Decode a G3B order-code string into readable fields.

    Never raises. Returns {} for anything it cannot confidently parse: wrong
    model family, empty/non-string input, or a string with no known segments.
    """
    if not isinstance(model, str) or not model.startswith(_SUPPORTED_MODEL_PREFIX):
        return {}
    if not isinstance(config, str) or not config:
        return {}

    attrs = {}
    try:
        tokens = config.split(".")
        if tokens and tokens[0]:
            attrs.update(_rating(tokens[0]))
        for token in tokens[1:]:
            if not token:
                continue
            decoder = _SEGMENT_DECODERS.get(token[0])
            if decoder is not None:
                attrs.update(decoder(token[1:]))
    except Exception:
        return {}
    return attrs
