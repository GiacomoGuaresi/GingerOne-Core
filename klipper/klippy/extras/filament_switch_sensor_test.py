import unittest
import time
from unittest.mock import MagicMock
from filament_switch_sensor_draft import RunoutHelper  

class TestRunoutHelper(unittest.TestCase):
    def setUp(self):
        self.runout_helper = RunoutHelper()
        
    # def test_single_true_call(self):
    #     print("--- Test single true call ---")
    #     self.runout_helper.note_filament_present(True)
    #     time.sleep(1.5)
    #     self.assertFalse(self.runout_helper.rele_result)

    # def test_single_false_call(self):
    #     print("--- Test single false call ---")
    #     self.runout_helper.note_filament_present(False)
    #     time.sleep(1.5)
    #     self.assertTrue(self.runout_helper.rele_result)

    def test_multiple_calls(self):
        print("--- Test multiple calls ---")
        # Setup iniziale del sensore
        print("Initial Setup")
        self.runout_helper.note_filament_present(True)
        time.sleep(1.5)
        
        # Chiamate in rapida successione
        print("Bouncing")
        self.runout_helper.note_filament_present(False)
        time.sleep(0.11)
        self.runout_helper.note_filament_present(True)
        time.sleep(0.11)
        self.runout_helper.note_filament_present(False)
        time.sleep(0.11)
        self.runout_helper.note_filament_present(True)
        time.sleep(0.11)
        self.runout_helper.note_filament_present(False)

        # Attesa per 0.5 secondi dall'ultima chiamata
        print("Check too soon")
        time.sleep(0.5)
        self.assertFalse(self.runout_helper.rele_result)

        # Attesa per 1 ulteriore secondo
        print("Corret check after 1 second")
        time.sleep(1)
        self.assertTrue(self.runout_helper.rele_result)

        time.sleep(5)
if __name__ == '__main__':
    unittest.main()
