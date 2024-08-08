import unittest
from rescalepy.session import Session
from test import RESCALE_API_KEY, TEST_CORE_TYPE, TEST_INPUT_FILES, TEST_SOFTWARE_CODE, TEST_SOFTWARE_VERSION


class TestResources(unittest.TestCase):

    def setUp(self):
        self.session = Session(api_token=RESCALE_API_KEY)

    def test_list_analyses(self):
        analyses = self.session.list_analyses()
        self.assertTrue(all(k in analyses[0] for k in ['category', 'name', 'code', 'versions']))

    def test_get_latest_software_version(self):
        version = self.session.get_latest_software_version(TEST_SOFTWARE_CODE)
        self.assertTrue(version.startswith('v'))

    def test_get_core_types(self):
        core_types = self.session.get_core_types()
        self.assertTrue(all(k in core_types[0] for k in ['code', 'name', 'price', 'cores', 'memory']))

    def test_get_cheapest_core(self):
        cheapest_core = self.session.get_cheapest_core()
        self.assertTrue(isinstance(cheapest_core, str) and cheapest_core != '')


class TestJob(unittest.TestCase):

    def setUp(self):
        self.session = Session(api_token=RESCALE_API_KEY)

    def test_1_create_job(self):
        self.job_id = self.session.create_job(
            name='Test Job',
            software_code=TEST_SOFTWARE_CODE,
            command='cd airfoil2D;./Allrun',
            input_files=TEST_INPUT_FILES,
            version=TEST_SOFTWARE_VERSION,
            core_type=TEST_CORE_TYPE
        )

        self.assertTrue(isinstance(self.job_id, str) and self.job_id != '')

    def test_2_submit_job(self):
        ...

    def test_3_get_job_status(self):
        ...

    def test_4_get_job_results(self):
        ...
