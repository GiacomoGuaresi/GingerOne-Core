# Ginger Pellet Sensor Module and feeder attivaction
# Overriwright original filament_swtich_sensor.py by Eric Callahan <arksine.code@gmail.com>
# Developed for the GingerOne Printer auto Feeder extension
#
# Copyright (C) 2024 Giacomo Guaresi <giacomo.guaresi@gmail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging
import asyncio

from datetime import datetime
import time

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
        self.debounce_time = config.getfloat('debounce_time', 1.0, above=0.0)
        self.emergency_time = config.getfloat('emergency_time', 10, minval=1)
        self.enable_emergency = config.getboolean('enable_emergency', True)
        self.rele_pin = config.get('rele_pin')
       
        # Internal state
        self.pellet_present = None
        self.sensor_enabled = True
        self.emergency_task = None
        self.last_state_change_time = time.time()
        self.last_action = None
        self.last_emergency_time = None

        # Register commands and event handlers
        self.gcode.register_mux_command(
            "QUERY_FILAMENT_SENSOR", "SENSOR", self.name,
            self.cmd_QUERY_FILAMENT_SENSOR,
            desc=self.cmd_QUERY_FILAMENT_SENSOR_help)
        self.gcode.register_mux_command(
            "SET_FILAMENT_SENSOR", "SENSOR", self.name,
            self.cmd_SET_FILAMENT_SENSOR,
            desc=self.cmd_SET_FILAMENT_SENSOR_help)
        #logging.info("filament_switch_sensor initialized")

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

        current_time = time.time()
        self.gcode.run_script("M118 triggered note_filament_present @ " + str(current_time) + " with status " + str(is_pellet_present))        

        # Verifica se il sensore è abilitato, se non lo è non fa nulla
        if not self.sensor_enabled:
            return
        
        # Verifica se la stampante è in stampa, nel caso non lo sia non fa nulla
        eventtime = self.reactor.monotonic()
        idle_timeout = self.printer.lookup_object("idle_timeout")
        is_printing = idle_timeout.get_status(eventtime)["state"] == "Printing"
        if not is_printing:
            # Se non è in stampa ma il feeder potrebbe essere acceso spegne e ritorna 
            if self.last_action != 'off':
                self.filledup()
            return

        # Verifica se lo stato attuale è diverso dallo stato precedente
        if is_pellet_present != self.pellet_present:
            # Aggiorna lo stato corrente e il timestamp dell'ultima modifica
            self.pellet_present = is_pellet_present
            self.last_state_change_time = current_time

            #logging.info("debounce started @ " + str(current_time) + " with status " + str(is_pellet_present))
            self.gcode.run_script("M118 debounce started @ " + str(current_time) + " with status " + str(is_pellet_present))
            # Resetta l'ultima azione
            self.last_action = None

            # chiama la funzione dopo il tempo di debonce 
            self.rerun_note_filament_present(is_pellet_present)

        else:
            # Calcola la differenza di tempo dall'ultima modifica
            time_diff = current_time - self.last_state_change_time

            #logging.info("check after " + str(time_diff))
            self.gcode.run_script("M118 check after " + str(time_diff))
            # Verifica se è passato più di 1 secondo
            if time_diff >= self.debounce_time:
                # Applica la logica di debounce
                if is_pellet_present and self.last_action != 'off':
                    #logging.info("execute filledup")
                    self.gcode.run_script("M118 execute filledup")
                    self.filledup()
                elif not is_pellet_present and self.last_action != 'on':
                    #logging.info("execute runout")
                    self.gcode.run_script("M118 execute runout")
                    self.runout()

        # Verifica la logica di emergenza
        if self.enable_emergency and self.last_emergency_time is not None:
            emergency_time_diff = current_time - self.last_emergency_time
            if emergency_time_diff >= 10.0:
                if self.emergency_gcode is not None:
                    self.emergency()

    async def rerun_note_filament_present(self, is_pellet_present):
        await asyncio.sleep(self.debounce_time + 0.1)
        self.gcode.run_script("M118 rerun_note_filament_present after debounce time")
        self.note_filament_present(is_pellet_present)

    def emergency(self):
        self.reactor.register_callback(self._emergency_event_handler)

    def runout(self):
        #self.reactor.register_callback(self._runout_event_handler)

        # Aggiorna il timestamp dell'ultima emergenza e l'ultima azione
        self.last_emergency_time = time.time()
        self.last_action = 'on'

    def filledup(self):
        #self.reactor.register_callback(self._filledup_event_handler)

        # Resettare il timestamp dell'emergenza quando il feeder viene spento e l'ultima azione
        self.last_emergency_time = None
        self.last_action = 'off'

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
#  debounce_time: 1.0
#     The time in seconds between each sample of the sensor. Default is
#     1.0 seconds.
#  emergency_time: 10
#     The time in seconds to wait before the emergency event is triggered.
#     Default is 10 seconds.
#  enable_emergency: True
#     When set to True, the emergency event is triggered after the
#     emergency_time is elapsed. Default is True.
#  rele_pin (NOT IMPLEMENTED YET):
#     The pin on which the feeder is connected. This parameter must be
#     provided.