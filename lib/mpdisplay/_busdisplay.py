# SPDX-FileCopyrightText: 2023 Kevin Schlosser and Brad Barnett
#
# SPDX-License-Identifier: MIT

'''
busdisplay.py - BusDisplay class for MicroPython
'''

from micropython import const, alloc_emergency_exception_buf
from time import sleep_ms
import struct
import sys

if sys.implementation.name == "micropython":
    from machine import Pin
elif sys.implementation.name == "circuitpython":
    import digitalio
else:
    raise NotImplementedError("Unsupported implementation")


alloc_emergency_exception_buf(256)

# MIPI DCS (Display Command Set) Command Constants
_INVOFF = const(0x20)
_INVON = const(0x21)
_CASET = const(0x2A)
_RASET = const(0x2B)
_RAMWR = const(0x2C)
_COLMOD = const(0x3A)
_MADCTL = const(0x36)
_SWRESET = const(0x01)
_SLPIN = const(0x10)
_SLPOUT = const(0x11)
_VSCRDEF = const(0x33)
_VSCSAD = const(0x37)

# MIPI DCS MADCTL bits
# Bits 0 (Flip Vertical) and 1 (Flip Horizontal) affect how the display is refreshed, not how frame memory is written.
# Instead of using them, we only change Bits 6 (column/horizontal) and 7 (page/vertical).
_RGB = const(0x00)  # (Bit 3: 0=RGB order, 1=BGR order)
_BGR = const(0x08)  # (Bit 3: 0=RGB order, 1=BGR order)
_MADCTL_MH = const(0x04)  # Refresh 0=Left to Right, 1=Right to Left (Bit 2: Display Data Latch Order)
_MADCTL_ML = const(0x10)  # Refresh 0=Top to Bottom, 1=Bottom to Top (Bit 4: Line Refresh Order)
_MADCTL_MV = const(0x20)  # 0=Normal, 1=Row/column exchange (Bit 5: Page/Column Addressing Order)
_MADCTL_MX = const(0x40)  # 0=Left to Right, 1=Right to Left (Bit 6: Column Address Order)
_MADCTL_MY = const(0x80)  # 0=Top to Bottom, 1=Bottom to Top (Bit 7: Page Address Order)

# MADCTL values for each of the rotation constants.
_DEFAULT_ROTATION_TABLE = (
    _MADCTL_MX,                            # mirrored = False, rotation = 0
    _MADCTL_MV,                            # mirrored = False, rotation = 90
    _MADCTL_MY,                            # mirrored = False, rotation = 180
    _MADCTL_MY | _MADCTL_MX | _MADCTL_MV,  # mirrored = False, rotation = 270
)

_MIRRORED_ROTATION_TABLE = (
    0,                                     # mirrored = True, rotation = 0
    _MADCTL_MV | _MADCTL_MX,               # mirrored = True, rotation = 90
    _MADCTL_MX | _MADCTL_MY,               # mirrored = True, rotation = 180
    _MADCTL_MV | _MADCTL_MY,               # mirrored = True, rotation = 270
)

_DEFAULT_TOUCH_ROTATION_TABLE = (0b000, 0b101, 0b110, 0b011)

class BusDisplay:
    class BusDisplay:
        """
        A class used to represent a display connected to a bus.

        This class provides the necessary interfaces to interact with a display
        connected to a bus. It allows setting various display parameters like
        width, height, rotation, color depth, brightness, etc.
        """
    display_name = "BusDisplay"

    def __init__(
        self,
        display_bus,
        init_sequence=None,
        *,
        width=0,
        height=0,
        colstart=0,
        rowstart=0,
        rotation=0,
        mirrored=False,
        color_depth=16,
        bgr=False,
        invert=False,
        reverse_bytes_in_word=False,
        brightness=1.0,
        backlight_pin=None,
        backlight_on_high=True,
        reset_pin=None,
        reset_high=True,
        power_pin=None,
        power_on_high=True,
        set_column_command=_CASET,
        set_row_command=_RASET,
        write_ram_command=_RAMWR,
        brightness_command=None,  # For color OLEDs
        data_as_commands=False,  # For color OLEDs
        single_byte_bounds=False,  # For color OLEDs
        touch_read_func = None,
        touch_rotation_table = _DEFAULT_TOUCH_ROTATION_TABLE,
    ):
        """
        Initializes the BusDisplay with the given parameters.

        :param display_bus: The bus to which the display is connected.
        :type display_bus: object
        :param width: The width of the display.
        :type width: int
        :param height: The height of the display.
        :type height: int
        :param colstart: The starting column of the display (default is 0).
        :type colstart: int, optional
        :param rowstart: The starting row of the display (default is 0).
        :type rowstart: int, optional
        :param rotation: The rotation of the display (default is 0).
        :type rotation: int, optional
        :param mirrored: Whether the display is mirrored (default is False).
        :type mirrored: bool, optional
        :param color_depth: The color depth of the display (default is 16).
        :type color_depth: int, optional
        :param bgr: Whether the display uses BGR color order (default is False).
        :type bgr: bool, optional
        :param invert: Whether the display colors are inverted (default is False).
        :type invert: bool, optional
        :param reverse_bytes_in_word: Whether the bytes in a word are reversed (default is False).
        :type reverse_bytes_in_word: bool, optional
        :param brightness: The brightness of the display (default is 1.0).
        :type brightness: float, optional
        :param backlight_pin: The pin number for the display backlight (default is None).
        :type backlight_pin: int, optional
        :param backlight_on_high: Whether the backlight is on when the pin is high (default is True).
        :type backlight_on_high: bool, optional
        :param reset_pin: The pin number for resetting the display (default is None).
        :type reset_pin: int, optional
        :param reset_high: Whether the display resets when the pin is high (default is True).
        :type reset_high: bool, optional
        """
        self.display_bus = display_bus
        self._width = width
        self._height = height
        self._colstart = colstart
        self._rowstart = rowstart
        self._rotation = rotation
        self.color_depth = color_depth
        self.bgr = bgr
        self.requires_byte_swap = reverse_bytes_in_word
        self._set_column_command = set_column_command
        self._set_row_command = set_row_command
        self._write_ram_command = write_ram_command
        self._brightness_command = brightness_command
        self._data_as_commands = data_as_commands  # not implemented
        self._single_byte_bounds = single_byte_bounds  # not implemented
        self._touch_read_func = touch_read_func if touch_read_func else lambda: None
        self._touch_rotation_table = touch_rotation_table

        self._reset_pin = self._config_pin_ouput(reset_pin, value=not reset_high)
        self._reset_high = reset_high

        self._power_pin = self._config_pin_ouput(power_pin, value=power_on_high)
        self._power_on_high = power_on_high

        self._backlight_pin = self._config_pin_ouput(backlight_pin, value=backlight_on_high)
        self._backlight_on_high = backlight_on_high

        if self._backlight_pin is not None:
            try:
                if sys.implementation.name == "micropython":
                    from machine import PWM
                    self._backlight_pin = PWM(self._backlight_pin, freq=1000, duty_u16=0)
                elif sys.implementation.name == "circuitpython":
                    from pwmio import PWMOut
                    self._backlight_pin = PWMOut(self._backlight_pin, frequency=1000, duty_cycle=0)
                else:
                    raise NotImplementedError("Unsupported implementation")
                self._backlight_is_pwm = True
            except ImportError:
                # PWM not implemented on this platform or Pin
                self._backlight_is_pwm = False

        self.set_window = self._set_window

        if hasattr(display_bus, "tx_color"):
            # lcd_bus and mp_lcd_bus use tx_color and tx_param to send color data and parameters
            self._send_cmd_data = display_bus.tx_param
            self._blit = display_bus.tx_color
        else:
            # CircuitPython uses send() to send color data and parameters
            self._send_cmd_data = display_bus.send
            self._blit = self.send_cmd_data

        self.rotation_table = _DEFAULT_ROTATION_TABLE if not mirrored else _MIRRORED_ROTATION_TABLE
        self._param_buf = bytearray(4)
        self._param_mv = memoryview(self._param_buf)

        if hasattr(display_bus, "init"):
            display_bus.init(
                self._width,
                self._height,
                self.color_depth,
                self._width * self._height * self.color_depth // 8,
                self.requires_byte_swap,
            )

        self._initialized = False
        if type(init_sequence) is bytes:
            self._init_bytes(init_sequence)
        elif type(init_sequence) is list or type(init_sequence) is tuple:
            self._init_list(init_sequence)
        self.init()
        if not self._initialized:
            raise RuntimeError(
                "Display driver init() must call super().init() or set self._initialized = True"
            )
        self.brightness = brightness
        if invert:
            self.invert_colors(True)
        self._colmod()

    def init(self, render_mode_full=False):
        """
        Post initialization tasks may be added here.
        
        This method may be overridden by subclasses to perform any post initialization.
        If it is overridden, it must call super().init() or set self._initialized = True.

        :param render_mode_full: Whether to set the display to render the full screen each
         time the .blit() method is called (default is False).
        :type render_mode_full: bool, optional
        """
        self._initialized = True
        self.rotation = self._rotation
        self.set_render_mode_full(render_mode_full)
        self.fill_rect(0, 0, self.width, self.height, 0x0)

    def blit(self, x, y, width, height, buf):
        """
        Blit a buffer to the display.

        This method takes a buffer of pixel data and writes it to a specified
        rectangular area of the display. The top-left corner of the rectangle is
        specified by the x and y parameters, and the size of the rectangle is
        specified by the width and height parameters.

        :param x: The x-coordinate of the top-left corner of the rectangle.
        :type x: int
        :param y: The y-coordinate of the top-left corner of the rectangle.
        :type y: int
        :param width: The width of the rectangle.
        :type width: int
        :param height: The height of the rectangle.
        :type height: int
        :param buf: The buffer containing the pixel data to be written to the display.
        :type buf: memoryview
        """
        x1 = x + self._colstart
        x2 = x1 + width - 1
        y1 = y + self._rowstart
        y2 = y1 + height - 1

        self.set_window(x1, y1, x2, y2)
        self._blit(self._write_ram_command, buf, x1, y1, x2, y2)

    def fill_rect(self, x, y, width, height, color):
        """
        Draw a rectangle at the given location, size and filled with color.

        This method draws a filled rectangle on the display. The top-left corner of
        the rectangle is specified by the x and y parameters, and the size of the
        rectangle is specified by the width and height parameters. The rectangle is
        filled with the specified color.

        :param x: The x-coordinate of the top-left corner of the rectangle.
        :type x: int
        :param y: The y-coordinate of the top-left corner of the rectangle.
        :type y: int
        :param width: The width of the rectangle in pixels.
        :type width: int
        :param height: The height of the rectangle in pixels.
        :type height: int
        :param color: The color to fill the rectangle with, encoded as a 565 color.
        :type color: int
        """
        if height > width:
            raw_data = struct.pack("<H", color) * height
            for col in range(x, x + width):
                self.blit(col, y, 1, height, memoryview(raw_data[:]))
        else:
            raw_data = struct.pack("<H", color) * width
            for row in range(y, y + height):
                self.blit(x, row, width, 1, memoryview(raw_data[:]))

    @property
    def width(self):
        """The width of the display in pixels."""
        if ((self._rotation // 90) & 0x1) == 0x1:  # if rotation index is odd
            return self._height
        return self._width

    @property
    def height(self):
        """The height of the display in pixels."""
        if ((self._rotation // 90) & 0x1) == 0x1:  # if rotation index is odd
            return self._width
        return self._height

    def set_render_mode_full(self, render_mode_full=False):
        """
        Set the render mode of the display.

        This method sets the render mode of the display. If the render_mode_full
        parameter is True, the display will be set to render the full screen each
        time the .blit() method is called. Otherwise, the window will be set each
        time the .blit() method is called.

        :param render_mode_full: Whether to set the display to render the full screen
         each time the .blit() method is called (default is False).
        :type render_mode_full: bool, optional
        """
        # If rendering the full screen, set the window now
        # and pass each time .blit() is called.
        if render_mode_full:
            self._set_window(0, 0, self.width, self.height)
            self.set_window = self._pass
        # Otherwise, set the window each time .blit() is called.
        else:
            self.set_window = self._set_window

    def bus_swap_disable(self, value):
        """
        Disable byte swapping in the display bus.

        If self.requires_bus_swap and the guest application is capable of byte swapping color data
        check to see if byte swapping can be disabled in the display bus.  If so, disable it.

        Guest applications that are capable of byte swapping should include:

            # If byte swapping is required and the display bus is capable of having byte swapping disabled,
            # disable it and set a flag so we can swap the color bytes as they are created.
            if display_drv.requires_byte_swap:
                swap_color_bytes = display_drv.bus_swap_disable(True)
            else:
                swap_color_bytes = False

        :param value: Whether to disable byte swapping in the display bus.
        :type value: bool
        :return: True if the bus swap was disabled, False if it was not.
        :rtype: bool
        """
        if hasattr(self.display_bus, "enable_swap"):
            self.display_bus.enable_swap(not value)
            return value
        return False

    def register_callback(self, callback):
        """
        Register a callback function.
        """
        if hasattr(self.display_bus, "register_callback"):
            self.display_bus.register_callback(callback)
        else:
            raise NotImplementedError(
                "register_callback() not implemented in display_bus.  Set blocking = True"
                )

    @property
    def power(self):
        """
        The power state of the display.
        
        :return: The power state of the display.
        :rtype: int
        """
        if self._power_pin is None:
            return -1

        state = self._power_pin.value()
        if self._power_on_high:
            return state

        return not state

    @power.setter
    def power(self, value):
        """
        Set the power state of the display.
        
        :param value: The power state to set.
        :type value: int
        """
        if self._power_pin is None:
            return

        if self._power_on_high:
            self._power_pin.value(value)
        else:
            self._power_pin.value(not value)

    @property
    def brightness(self):
        """
        The brightness of the display.

        :return: The brightness of the display.
        :rtype: float
        """
        if self._backlight_pin is None and self._brightness_command is None:
            return -1

        return self._brightness

    @brightness.setter
    def brightness(self, value):
        """
        Set the brightness of the display.

        :param value: The brightness to set.
        :type value: float
        """
        if 0 <= float(value) <= 1.0:
            self._brightness = value
            if self._backlight_pin:
                if not self._backlight_on_high:
                    value = 1.0 - value
                if self._backlight_is_pwm:
                    if sys.implementation.name == "micropython":
                        self._backlight_pin.duty_u16(int(value * 0xFFFF))
                    elif sys.implementation.name == "circuitpython":
                        self._backlight_pin.duty_cycle = int(value * 0xFFFF)
                else:
                    self._backlight_pin.value(value > 0.5)
            elif self._brightness_command is not None:
                self.send_cmd_data(self._brightness_command, struct.pack("B", int(value * 255)))

    def reset(self):
        """
        Reset display.

        This method resets the display. If the display has a reset pin, it is
        reset using the reset pin. Otherwise, the display is reset using the
        software reset command.
        """
        if self._reset_pin is not None:
            self.hard_reset()
        else:
            self.soft_reset()

    def hard_reset(self):
        """
        Hard reset display.
        """
        self._reset_pin.value(self._reset_high)
        sleep_ms(120)
        self._reset_pin.value(not self._reset_high)

    def soft_reset(self):
        """
        Soft reset display.
        """
        self.send_cmd_data(_SWRESET)
        sleep_ms(150)

    @property
    def rotation(self):
        """
        The rotation of the display.

        :return: The rotation of the display.
        :rtype: int
        """
        return self._rotation

    @rotation.setter
    def rotation(self, value):
        """
        Set the rotation of the display.

        :param value: The rotation to set.
        :type value: int
        """
        self._rotation = value

        # Set the display MADCTL bits for the given rotation.
        self._param_buf[0] = self._madctl(self.bgr, value, self.rotation_table)
        self.send_cmd_data(_MADCTL, self._param_mv[:1])

        # Set the touch rotation mask for the given rotation.
        index = (value // 90) % len(self._touch_rotation_table)
        mask = self._touch_rotation_table[index]
        self.set_touch_rotation_mask(mask)

    def sleep_mode(self, value):
        """
        Enable or disable display sleep mode.

        :param value: If True, enable sleep mode. If False, disable sleep mode.
        :type value: bool
        """
        if value:
            self.send_cmd_data(_SLPIN)
        else:
            self.send_cmd_data(_SLPOUT)

    def vscrdef(self, tfa, vsa, bfa):
        """
        Set Vertical Scrolling Definition.

        To scroll a 135x240 display these values should be 40, 240, 40.
        There are 40 lines above the display that are not shown followed by
        240 lines that are shown followed by 40 more lines that are not shown.
        You could write to these areas off display and scroll them into view by
        changing the TFA, VSA and BFA values.

        :param tfa: Top Fixed Area
        :type tfa: int
        :param vsa: Vertical Scrolling Area
        :type vsa: int
        :param bfa: Bottom Fixed Area
        :type bfa: int
        """
        self.send_cmd_data(_VSCRDEF, struct.pack(">HHH", tfa, vsa, bfa))

    def vscsad(self, vssa):
        """
        Set Vertical Scroll Start Address of RAM.

        Defines which line in the Frame Memory will be written as the first
        line after the last line of the Top Fixed Area on the display.

        Example:

            for line in range(40, 280, 1):
                tft.vscsad(line)
                utime.sleep(0.01)

        :param vssa: Vertical Scrolling Start Address
        :type vssa: int
        """
        self.send_cmd_data(_VSCSAD, struct.pack(">H", vssa))

    def invert_colors(self, value):
        """
        Invert the colors of the display.

        :param value: If True, invert the colors of the display. If False, do not invert the colors of the display.
        :type value: bool
        """
        if value:
            self.send_cmd_data(_INVON)
        else:
            self.send_cmd_data(_INVOFF)

    def send_cmd_data(self, cmd, params=None, *args, **kwargs):
        """
        Send cmd and parameters to the display.

        :param cmd: The command to send.
        :type cmd: int
        :param params: The parameters to send.
        :type params: bytes
        """
        self._send_cmd_data(cmd, params)

    def _pass(*_, **__):
        """Do nothing.  Used to replace self.set_window when render_mode_full is True."""
        pass

    def _set_window(self, x1, y1, x2, y2):
        """
        Set the window for the display.

        :param x1: The x-coordinate of the top-left corner of the window.
        :type x1: int
        :param y1: The y-coordinate of the top-left corner of the window.
        :type y1: int
        :param x2: The x-coordinate of the bottom-right corner of the window.
        :type x2: int
        :param y2: The y-coordinate of the bottom-right corner of the window.
        :type y2: int
        """
        # See https://github.com/adafruit/Adafruit_Blinka_Displayio/blob/main/displayio/_displaycore.py#L271-L363
        # TODO:  Add `if self._single_byte_bounds is True:` for Column and Row _param_buf packing

        # Column addresses
        self._param_buf[0] = (x1 >> 8) & 0xFF
        self._param_buf[1] = x1 & 0xFF
        self._param_buf[2] = (x2 >> 8) & 0xFF
        self._param_buf[3] = x2 & 0xFF
        self.send_cmd_data(self._set_column_command, self._param_mv[:4])

        # Row addresses
        self._param_buf[0] = (y1 >> 8) & 0xFF
        self._param_buf[1] = y1 & 0xFF
        self._param_buf[2] = (y2 >> 8) & 0xFF
        self._param_buf[3] = y2 & 0xFF
        self.send_cmd_data(self._set_row_command, self._param_mv[:4])

    @staticmethod
    def _madctl(bgr, rotation, rotations):
        """
        Return the MADCTL value for the given rotation.

        :param bgr: Whether the display uses BGR color order.
        :type bgr: bool
        :param rotation: The rotation of the display.
        :type rotation: int
        :param rotations: The rotation table.
        :type rotations: tuple
        :return: The MADCTL value for the given rotation.
        :rtype: int
        """
        # Convert from degrees to one quarter rotations.  Wrap at the number of entries in the rotations table.
        # For example, rotation = 90 -> index = 1.  With 4 entries in the rotation table, rotation = 540 -> index = 2
        index = (rotation // 90) % len(rotations)
        return rotations[index] | _BGR if bgr else _RGB

    def _colmod(self):
        """
        Set the color mode for the display.
        """
        pixel_formats = {3: 0x11, 8: 0x22, 12: 0x33, 16: 0x55, 18: 0x66, 24: 0x77}
        self._param_buf[0] = pixel_formats[self.color_depth]
        self.send_cmd_data(_COLMOD, self._param_mv[:1])

    def _init_bytes(self, init_sequence):
        """
        Send an initialization sequence to the display.

        Used by display driver subclass if init_sequence is a CircuitPython displayIO compatible bytes object.
        The ``init_sequence`` is bitpacked to minimize the ram impact. Every command begins
        with a command byte followed by a byte to determine the parameter count and if a
        delay is need after. When the top bit of the second byte is 1, the next byte will be
        the delay time in milliseconds. The remaining 7 bits are the parameter count
        excluding any delay byte. The third through final bytes are the remaining command
        parameters. The next byte will begin a new command definition.

        :param init_sequence: The initialization sequence to send to the display.
        :type init_sequence: bytearray
        """
        DELAY = 0x80

        i = 0
        while i < len(init_sequence):
            command = init_sequence[i]
            data_size = init_sequence[i + 1]
            delay = (data_size & DELAY) != 0
            data_size &= ~DELAY

            self.send_cmd_data(command, init_sequence[i + 2 : i + 2 + data_size])

            delay_time_ms = 10
            if delay:
                data_size += 1
                delay_time_ms = init_sequence[i + 1 + data_size]
                if delay_time_ms == 255:
                    delay_time_ms = 500

            sleep_ms(delay_time_ms)
            i += 2 + data_size

    def _init_list(self, init_sequence):
        """
        Send an initialization sequence to the display.

        Used by display driver subclass if init_sequence is a list of tuples.
        As a list, it can be modified in .init(), for example:
            self._INIT_SEQUENCE[-1] = (0x29, b"\x00", 100)
        Each tuple contains the following:
            - The first element is the register address (command)
            - The second element is the register value (data)
            - The third element is the delay in milliseconds after the register is set

        :param init_sequence: The initialization sequence to send to the display.
        :type init_sequence: list
        """
        for line in init_sequence:
            self.send_cmd_data(line[0], line[1])
            if line[2] != 0:
                sleep_ms(line[2])

    def get_touched(self):
        # touch_read_func should return None, a point as a tuple (x, y), a point as a list [x, y] or
        # a tuple / list of points ((x1, y1), (x2, y2)), [(x1, y1), (x2, y2)], ([x1, y1], [x2, y2]),
        # or [[x1, y1], [x2, y2]].  If it doesn't, create a wrapper around your driver's read function
        # and set touch_read_func to that wrapper, or subclass TouchDriver and override .get_touched()
        # with your own logic.  A point tuple/list may have additional values other than x and y that
        # are ignored.  x and y must come first.  Some multi-touch drivers may return extra data such
        # as the index of the touch point (1st, 2nd, etc).  Only the first point in the list will be
        # used and any extra data in that point will be ignored.
        touched = self._touch_read_func()
        if touched:
            # If it looks like a point, use it, otherwise get the first point out of the list / tuple
            (x, y, *_) = touched if isinstance(touched[0], int) else touched[0]
            if self._touch_swap_xy:
                x, y = y, x
            if self._touch_invert_x:
                x = self.width - x - 1
            if self._touch_invert_y:
                y = self.height - y - 1
            return x, y
        return None

    def set_touch_rotation_mask(self, mask):
        # mask is an integer from 0 to 7 (or 0b001 to 0b111, 3 bits)
        # Currently, bit 2 = invert_y, bit 1 is invert_x and bit 0 is swap_xy, but that may change.
        # Your display driver should have a way to set rotation, but your touch driver may not have a way to set
        # its rotation.  You can call this function any time after you've created devices to change the rotation.
        mask = mask & 0b111
        self._touch_invert_y = True if mask >> 2 & 1 else False
        self._touch_invert_x = True if mask >> 1 & 1 else False
        self._touch_swap_xy = True if mask >> 0 & 1 else False

    def _config_pin_ouput(self, pin, value=None):
        if pin is None:
            return None
        
        if sys.implementation.name == "micropython":
            p = Pin(pin, Pin.OUT)
        elif sys.implementation.name == "circuitpython":
            p = digitalio.DigitalInOut(pin)
            p.direction = digitalio.Direction.OUTPUT

        if value is not None:
            p.value(value)
        return p