import os
import sys

# Testler depo kökündeki modülleri (logic, utils) içe aktarır
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
