from pathlib import Path

import keyring

RESCALE_API_KEY = keyring.get_password('rescale_api', 'bthorn191@gmail.com')
TEST_SOFTWARE_CODE = 'openfoam_plus'
TEST_SOFTWARE_VERSION = 'v1812+-intelmpi'
TEST_CORE_TYPE = 'emerald_max'
TEST_INPUT_FILES = [Path(__file__).parent / 'job/airfoil2D.zip']
