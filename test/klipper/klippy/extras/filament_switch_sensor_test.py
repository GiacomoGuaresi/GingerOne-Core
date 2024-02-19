import unittest
from unittest.mock import MagicMock, patch
import os
import sys

# Aggiungi il percorso del progetto alla sys.path
project_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../"))
sys.path.insert(0, project_path)

# Ora puoi importare il modulo
from klipper.klippy.extras.filament_switch_sensor import RunoutHelper

class TestRunoutHelper(unittest.TestCase):

    def setUp(self):
        # Create a mock config for testing
        self.mock_config = MagicMock()

    def test_init(self):
        # Test the initialization of RunoutHelper
        with patch('klipper.klippy.extras.filament_switch_sensor.RunoutHelper._exec_gcode') as mock_exec_gcode:
            runout_helper = RunoutHelper(self.mock_config)

            # Assert that the initialization sets up the necessary attributes
            self.assertEqual(runout_helper.pellet_present, False)
            self.assertEqual(runout_helper.sensor_enabled, True)
            self.assertEqual(runout_helper.feeder_status, False)

            # Assert that the _exec_gcode method is called with the correct arguments
            mock_exec_gcode.assert_called_once_with("", runout_helper.runout_gcode)

    def test_note_filament_present(self):
        # Test the note_filament_present method
        runout_helper = RunoutHelper(self.mock_config)

        # Mock the reactor and idle_timeout for testing
        mock_reactor = MagicMock()
        mock_idle_timeout = MagicMock()
        runout_helper.reactor = mock_reactor
        runout_helper.printer.lookup_object.return_value = mock_idle_timeout

        # Mock the _exec_gcode method
        with patch('klipper.klippy.extras.filament_switch_sensor.RunoutHelper._exec_gcode') as mock_exec_gcode:
            # Test when pellet is present and sensor is enabled
            runout_helper.note_filament_present(True)
            mock_exec_gcode.assert_called_once_with("", runout_helper.filledup_gcode)
            mock_reactor.pause.assert_not_called()

            # Test when pellet is not present and printer is printing
            mock_exec_gcode.reset_mock()
            runout_helper.note_filament_present(False)
            mock_exec_gcode.assert_called_once_with("", runout_helper.runout_gcode)
            mock_reactor.pause.assert_called_once()

            # Test when pellet is not present and printer is not printing
            mock_exec_gcode.reset_mock()
            mock_idle_timeout.get_status.return_value = {"state": "Idle"}
            runout_helper.note_filament_present(False)
            mock_exec_gcode.assert_not_called()
            mock_reactor.pause.assert_not_called()

    # Add more test cases as needed

if __name__ == '__main__':
    unittest.main()
