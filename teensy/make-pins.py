#!/usr/bin/env python
"""Creates the pin file for the Teensy."""

from __future__ import print_function

import argparse
import sys
import csv

SUPPORTED_FN = {
    'FTM'   : ['CH0',  'CH1',  'CH2',  'CH3',
               'QD_PHA', 'QD_PHB'],
    'I2C'   : ['SDA', 'SCL'],
    'UART'  : ['RX', 'TX', 'CTS', 'RTS'],
    'SPI'   : ['NSS', 'SCK', 'MISO', 'MOSI']
}

def parse_port_pin(name_str):
    """Parses a string and returns a (port-num, pin-num) tuple."""
    if len(name_str) < 4:
        raise ValueError("Expecting pin name to be at least 4 charcters.")
    if name_str[0:2] != 'PT':
        raise ValueError("Expecting pin name to start with PT")
    if name_str[2] not in ('A', 'B', 'C', 'D', 'E', 'Z'):
        raise ValueError("Expecting pin port to be between A and E or Z")
    port = ord(name_str[2]) - ord('A')
    pin_str = name_str[3:].split('/')[0]
    if not pin_str.isdigit():
        raise ValueError("Expecting numeric pin number.")
    return (port, int(pin_str))

def split_name_num(name_num):
    num = None
    for num_idx in range(len(name_num) - 1, -1, -1):
        if not name_num[num_idx].isdigit():
            name = name_num[0:num_idx + 1]
            num_str = name_num[num_idx + 1:]
            if len(num_str) > 0:
                num = int(num_str)
            break
    return name, num


class AlternateFunction(object):
    """Holds the information associated with a pins alternate function."""

    def __init__(self, idx, af_str):
        self.idx = idx
        self.af_str = af_str

        self.func = ''
        self.fn_num = None
        self.pin_type = ''
        self.supported = False

        af_words = af_str.split('_', 1)
        self.func, self.fn_num = split_name_num(af_words[0])
        if len(af_words) > 1:
            self.pin_type = af_words[1]
        if self.func in SUPPORTED_FN:
            pin_types = SUPPORTED_FN[self.func]
            if self.pin_type in pin_types:
                self.supported = True

    def is_supported(self):
        return self.supported

    def ptr(self):
        """Returns the numbered function (i.e. USART6) for this AF."""
        if self.fn_num is None:
            return self.func
        return '{:s}{:d}'.format(self.func, self.fn_num)

    def print(self):
        """Prints the C representation of this AF."""
        if self.supported:
            print('  AF',  end='')
        else:
            print('  //', end='')
        fn_num = self.fn_num
        if fn_num is None:
            fn_num = 0
        print('({:2d}, {:8s}, {:2d}, {:10s}, {:8s}), // {:s}'.format(self.idx,
              self.func, fn_num, self.pin_type, self.ptr(), self.af_str))


class Pin(object):
    """Holds the information associated with a pin."""

    def __init__(self, port, pin):
        self.port = port
        self.pin = pin
        self.alt_fn = []
        self.alt_fn_count = 0
        self.adc_num = 0
        self.adc_channel = 0
        self.board_pin = False

    def port_letter(self):
        return chr(self.port + ord('A'))

    def cpu_pin_name(self):
        return '{:s}{:d}'.format(self.port_letter(), self.pin)

    def is_board_pin(self):
        return self.board_pin

    def set_is_board_pin(self):
        self.board_pin = True

    def parse_adc(self, adc_str):
        if (adc_str[:3] != 'ADC'):
            return
        (adc,channel) = adc_str.split('_')
        for idx in range(3, len(adc)):
            adc_num = int(adc[idx]) # 1, 2, or 3
            self.adc_num |= (1 << (adc_num - 1))
        self.adc_channel = int(channel[2:])

    def parse_af(self, af_idx, af_strs_in):
        if len(af_strs_in) == 0:
            return
        # If there is a slash, then the slash separates 2 aliases for the
        # same alternate function.
        af_strs = af_strs_in.split('/')
        for af_str in af_strs:
            alt_fn = AlternateFunction(af_idx, af_str)
            self.alt_fn.append(alt_fn)
            if alt_fn.is_supported():
                self.alt_fn_count += 1

    def alt_fn_name(self, null_if_0=False):
        if null_if_0 and self.alt_fn_count == 0:
            return 'NULL'
        return 'pin_{:s}_af'.format(self.cpu_pin_name())

    def adc_num_str(self):
        str = ''
        for adc_num in range(1,4):
            if self.adc_num & (1 << (adc_num - 1)):
                if len(str) > 0:
                    str += ' | '
                str += 'PIN_ADC'
                str += chr(ord('0') + adc_num)
        if len(str) == 0:
            str = '0'
        return str

    def print(self):
        if self.alt_fn_count == 0:
            print("// ",  end='')
        print('const pin_af_obj_t {:s}[] = {{'.format(self.alt_fn_name()))
        for alt_fn in self.alt_fn:
            alt_fn.print()
        if self.alt_fn_count == 0:
            print("// ",  end='')
        print('};')
        print('')
        print('const pin_obj_t pin_{:s} = PIN({:s}, {:d}, {:d}, {:s}, {:s}, {:d});'.format(
            self.cpu_pin_name(), self.port_letter(), self.pin,
            self.alt_fn_count, self.alt_fn_name(null_if_0=True),
            self.adc_num_str(), self.adc_channel))
        print('')

    def print_header(self, hdr_file):
        hdr_file.write('extern const pin_obj_t pin_{:s};\n'.
                       format(self.cpu_pin_name()))
        if self.alt_fn_count > 0:
            hdr_file.write('extern const pin_af_obj_t pin_{:s}_af[];\n'.
                           format(self.cpu_pin_name()))

class NamedPin(object):

    def __init__(self, name, pin):
        self._name = name
        self._pin = pin

    def pin(self):
        return self._pin

    def name(self):
        return self._name


class Pins(object):

    def __init__(self):
        self.cpu_pins = []   # list of NamedPin objects
        self.board_pins = [] # list of NamedPin objects

    def find_pin(self, port_num, pin_num):
        for named_pin in self.cpu_pins:
            pin = named_pin.pin()
            if pin.port == port_num and pin.pin == pin_num:
                return pin

    def parse_af_file(self, filename, pinname_col, af_col):
        with open(filename, 'r') as csvfile:
            rows = csv.reader(csvfile)
            for row in rows:
                try:
                    (port_num, pin_num) = parse_port_pin(row[pinname_col])
                except:
                    continue
                pin = Pin(port_num, pin_num)
                for af_idx in range(af_col, len(row)):
                    if af_idx >= af_col:
                        pin.parse_af(af_idx - af_col, row[af_idx])
                self.cpu_pins.append(NamedPin(pin.cpu_pin_name(), pin))

    def parse_board_file(self, filename):
        with open(filename, 'r') as csvfile:
            rows = csv.reader(csvfile)
            for row in rows:
                try:
                    (port_num, pin_num) = parse_port_pin(row[1])
                except:
                    continue
                pin = self.find_pin(port_num, pin_num)
                if pin:
                    pin.set_is_board_pin()
                    self.board_pins.append(NamedPin(row[0], pin))

    def print_named(self, label, named_pins):
        print('const pin_named_pin_t pin_{:s}_pins[] = {{'.format(label))
        for named_pin in named_pins:
            pin = named_pin.pin()
            if pin.is_board_pin():
                print('  {{ "{:s}", &pin_{:s} }},'.format(named_pin.name(),  pin.cpu_pin_name()))
        print('  { NULL, NULL }')
        print('};')

    def print(self):
        for named_pin in self.cpu_pins:
            pin = named_pin.pin()
            if pin.is_board_pin():
                pin.print()
        self.print_named('cpu', self.cpu_pins)
        print('')
        self.print_named('board', self.board_pins)

    def print_adc(self, adc_num):
        print('');
        print('const pin_obj_t * const pin_adc{:d}[] = {{'.format(adc_num))
        for channel in range(16):
            adc_found = False
            for named_pin in self.cpu_pins:
                pin = named_pin.pin()
                if (pin.is_board_pin() and
                    (pin.adc_num & (1 << (adc_num - 1))) and (pin.adc_channel == channel)):
                    print('  &pin_{:s}, // {:d}'.format(pin.cpu_pin_name(), channel))
                    adc_found = True
                    break
            if not adc_found:
                print('  NULL,    // {:d}'.format(channel))
        print('};')


    def print_header(self, hdr_filename):
        with open(hdr_filename, 'wt') as hdr_file:
            for named_pin in self.cpu_pins:
                pin = named_pin.pin()
                if pin.is_board_pin():
                    pin.print_header(hdr_file)
            hdr_file.write('extern const pin_obj_t * const pin_adc1[];\n')
            hdr_file.write('extern const pin_obj_t * const pin_adc2[];\n')
            hdr_file.write('extern const pin_obj_t * const pin_adc3[];\n')


def main():
    parser = argparse.ArgumentParser(
        prog="make-pins.py",
        usage="%(prog)s [options] [command]",
        description="Generate board specific pin file"
    )
    parser.add_argument(
        "-a", "--af",
        dest="af_filename",
        help="Specifies the alternate function file for the chip",
        default="stm32f4xx-af.csv"
    )
    parser.add_argument(
        "-b", "--board",
        dest="board_filename",
        help="Specifies the board file",
    )
    parser.add_argument(
        "-p", "--prefix",
        dest="prefix_filename",
        help="Specifies beginning portion of generated pins file",
        default="stm32f4xx-prefix.c"
    )
    parser.add_argument(
        "-r", "--hdr",
        dest="hdr_filename",
        help="Specifies name of generated pin header file",
        default="build/pins.h"
    )
    args = parser.parse_args(sys.argv[1:])

    pins = Pins()

    print('// This file was automatically generated by make-pins.py')
    print('//')
    if args.af_filename:
        print('// --af {:s}'.format(args.af_filename))
        pins.parse_af_file(args.af_filename, 4, 3)

    if args.board_filename:
        print('// --board {:s}'.format(args.board_filename))
        pins.parse_board_file(args.board_filename)

    if args.prefix_filename:
        print('// --prefix {:s}'.format(args.prefix_filename))
        print('')
        with open(args.prefix_filename, 'r') as prefix_file:
            print(prefix_file.read())
    pins.print()
    pins.print_adc(1)
    pins.print_adc(2)
    pins.print_adc(3)
    pins.print_header(args.hdr_filename)


if __name__ == "__main__":
    main()
