from pathlib import Path
from rescalepy.config import KEYRING_SERVICE, KEYRING_USERNAME
import keyring

RESCALE_API_KEY = keyring.get_password(f'test_{KEYRING_SERVICE}', KEYRING_USERNAME)
TEST_SOFTWARE_CODE = 'openfoam_plus'
TEST_SOFTWARE_VERSION = 'v1712+-intelmpi'
TEST_CORE_TYPE = 'emerald_max'
TEST_PROJECT_ID = 'gxzXS'
TEST_INPUT_FILES = [Path(__file__).parent / 'job/airfoil2D']
