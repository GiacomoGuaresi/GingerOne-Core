# Ginger Pellet Sensor Module and feeder attivaction
# Overriwright original filament_swtich_sensor.py by Eric Callahan <arksine.code@gmail.com>
# Developed for the GingerOne Printer auto Feeder extension
#
# Copyright (C) 2024 Giacomo Guaresi <giacomo.guaresi@gmail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging
import asyncio

class RunoutHelper:
    def __init__(self, config):
        self.name = config.get_name().split()[-1]
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object('gcode')
                
        # Read config
        self.runout_pause = config.getboolean('pause_on_runout', False)
        if self.runout_pause:
            self.printer.load_object(config, 'pause_resume')
        self.runout_gcode = self.filledup_gcode = None
        gcode_macro = self.printer.load_object(config, 'gcode_macro')
        if self.runout_pause or config.get('runout_gcode', None) is not None:
            self.runout_gcode = gcode_macro.load_template(
                config, 'runout_gcode', '')
        if config.get('filledup_gcode', None) is not None:
            self.filledup_gcode = gcode_macro.load_template(
                config, 'filledup_gcode')
        if config.get('emergency_gcode', None) is not None:
            self.emergency_gcode = gcode_macro.load_template(
                config, 'emergency_gcode')
        self.debounce_sample_time = config.getfloat('debounce_sample_time', .1, above=.0)
        self.debounce_sample_number = config.getint('debounce_sample_number', 10, minval=1)
        self.emergency_time = config.getfloat('emergency_time', 10, minval=1)
        self.enable_emergency = config.getboolean('enable_emergency', True)
        self.rele_pin = config.get('rele_pin')

        # Internal state
        self.min_event_systime = self.reactor.NEVER
        self.pellet_present = False
        self.sensor_enabled = True
        self.feeder_status = False
        
        # Register commands and event handlers
        self.gcode.register_mux_command(
            "QUERY_FILAMENT_SENSOR", "SENSOR", self.name,
            self.cmd_QUERY_FILAMENT_SENSOR,
            desc=self.cmd_QUERY_FILAMENT_SENSOR_help)
        self.gcode.register_mux_command(
            "SET_FILAMENT_SENSOR", "SENSOR", self.name,
            self.cmd_SET_FILAMENT_SENSOR,
            desc=self.cmd_SET_FILAMENT_SENSOR_help)
        
    def _runout_event_handler(self, eventtime):
        # Pausing from inside an event requires that the pause portion
        # of pause_resume execute immediately.
        pause_prefix = ""
        if self.runout_pause:
            pause_resume = self.printer.lookup_object('pause_resume')
            pause_resume.send_pause_command()
            pause_prefix = "PAUSE\n"
            self.printer.get_reactor().pause(eventtime + 0.5)
        self._exec_gcode(pause_prefix, self.runout_gcode)
        
    def _filledup_event_handler(self, eventtime):
        self._exec_gcode("", self.filledup_gcode)

    def _emergency_event_handler(self, eventtime):
        self._exec_gcode("", self.emergency_gcode)

    def _exec_gcode(self, prefix, template):
        try:
            self.gcode.run_script(prefix + template.render() + "\nM400")
        except Exception:
            logging.exception("Script running error")

    def note_filament_present(self, is_pellet_present):
        if is_pellet_present == self.pellet_present:
            return
        self.pellet_present = is_pellet_present
        
        # Perform pellet action associated with status change (if any)            
        logging.info("start or restart Debounce")
        asyncio.run(self.debounce_logic())

    def get_status(self, eventtime):
        return {
            "filament_detected": bool(self.pellet_present),
            "enabled": bool(self.sensor_enabled)}
    cmd_QUERY_FILAMENT_SENSOR_help = "Query the status of the pellet Sensor"
    def cmd_QUERY_FILAMENT_SENSOR(self, gcmd):
        if self.pellet_present:
            msg = "Pellet Sensor %s: pellet detected" % (self.name)
        else:
            msg = "Pellet Sensor %s: pellet not detected" % (self.name)
        gcmd.respond_info(msg)
    cmd_SET_FILAMENT_SENSOR_help = "Sets the pellet sensor on/off"
    def cmd_SET_FILAMENT_SENSOR(self, gcmd):
        self.sensor_enabled = gcmd.get_int("ENABLE", 1)

    async def debounce_logic(self):
        pellet_present_reference = self.pellet_present
        
        for _ in range(self.debounce_sample_number):
            await asyncio.sleep(self.debounce_sample_time) 
            if pellet_present_reference != self.pellet_present:
                return
        
        eventtime = self.reactor.monotonic()
        if not self.sensor_enabled:
            # do not process when the sensor is disabled
            return

        # Determine "printing" status
        idle_timeout = self.printer.lookup_object("idle_timeout")
        is_printing = idle_timeout.get_status(eventtime)["state"] == "Printing"
        
        if self.pellet_present:
            # filledup detected
            if self.filledup_gcode is not None:
                logging.info("Pellet Sensor %s: filledup event detected, Time %.2f" % (self.name, eventtime))
                self.turn_off_feeder()
        elif is_printing:
            # runout detected
            if self.runout_gcode is not None:
                logging.info("Pellet Sensor %s: runout event detected, Time %.2f" % (self.name, eventtime))
                self.turn_on_feeder()
    
    def turn_on_feeder(self):
        self.reactor.register_callback(self._runout_event_handler)
        if self.feeder_status == True:
            return
        
        logging.info("Turn ON feeder")
        self.feeder_status = True

        #TODO: set the pin to HIGH

        if self.enable_emergency:
            #start or stop&start emergency timer
            if self.emergency_task and not self.emergency_task.done():
                self.emergency_task.cancel()
            self.emergency_task = asyncio.create_task(self.emergency_stop_feeder())

    def turn_off_feeder(self):
        self.reactor.register_callback(self._filledup_event_handler)
        if self.feeder_status == False:
            return
        logging.info("Turn OFF feeder")
        self.feeder_status = False

        #TODO: set the pin to LOW

        if self.enable_emergency:
            #stop emergency timer
            if self.emergency_task and not self.emergency_task.done():
                self.emergency_task.cancel()
        
    async def emergency_stop_feeder(self):
        await asyncio.sleep(self.emergency_time)  
        logging.info("Emergency stop feeder")
        if self.emergency_gcode is not None:
            self.reactor.register_callback(self._emergency_event_handler)

        #TODO: play emergency Tone 
        #TODO: set the pin to LOW

class SwitchSensor:
    def __init__(self, config):
        printer = config.get_printer()
        buttons = printer.load_object(config, 'buttons')
        sensor_pin = config.get('sensor_pin')
        buttons.register_buttons([sensor_pin], self._button_handler)
        self.runout_helper = RunoutHelper(config)
        self.get_status = self.runout_helper.get_status
    def _button_handler(self, eventtime, state):
        self.runout_helper.note_filament_present(state)

def load_config_prefix(config):
    return SwitchSensor(config)

# [filament_switch_sensor my_sensor]
#  pause_on_runout: False
#     When set to True, a PAUSE will execute immediately after a runout
#     is detected. Note that if pause_on_runout is False and the
#     runout_gcode is omitted then runout detection is disabled. Default
#     is True.
#  runout_gcode:
#     A list of G-Code commands to execute after the pellet runout is
#     detected. See docs/Command_Templates.md for G-Code format. If
#     pause_on_runout is set to True this G-Code will run after the
#     PAUSE is complete. The default is not to run any G-Code commands.
#  filledup_gcode:
#     A list of G-Code commands to execute after the pellet insert is
#     detected. See docs/Command_Templates.md for G-Code format. The
#     default is not to run any G-Code commands, which disables insert
#     detection.
#  emergency_gcode:
#     A list of G-Code commands to execute after the emergency time is
#     elapsed. See docs/Command_Templates.md for G-Code format. The
#     default is not to run any G-Code commands, which disables emergency
#     detection.
#  sensor_pin:
#     The pin on which the sensor is connected. This parameter must be
#     provided.
#  debounce_sample_time: 0.1
#     The time in seconds between each sample of the sensor. Default is
#     0.1 seconds.
#  debounce_sample_number: 10
#     The number of samples to take before the sensor state is considered  
#     stable. Default is 10 samples.
#  emergency_time: 10
#     The time in seconds to wait before the emergency event is triggered.
#     Default is 10 seconds.
#  enable_emergency: True
#     When set to True, the emergency event is triggered after the
#     emergency_time is elapsed. Default is True.
#  rele_pin (NOT IMPLEMENTED YET):
#     The pin on which the feeder is connected. This parameter must be
#     provided.