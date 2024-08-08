from pathlib import Path
import tempfile
import unittest
from rescalepy.client import Client
from test import RESCALE_API_KEY, TEST_CORE_TYPE, TEST_INPUT_FILES, TEST_PROJECT_ID, TEST_SOFTWARE_CODE, TEST_SOFTWARE_VERSION


class TestResources(unittest.TestCase):

    def setUp(self):
        self.client = Client(api_token=RESCALE_API_KEY)

    def test_list_analyses(self):
        analyses = self.client.list_analyses()
        self.assertTrue(all(k in analyses[0] for k in ['category', 'name', 'code', 'versions']))

    def test_get_latest_software_version(self):
        version = self.client.get_latest_software_version(TEST_SOFTWARE_CODE)
        self.assertTrue(version.startswith('v'))

    def test_get_core_types(self):
        core_types = self.client.get_core_types()
        self.assertTrue(all(k in core_types[0] for k in ['code', 'name', 'price', 'cores', 'memory']))

    def test_get_cheapest_core(self):
        cheapest_core = self.client.get_cheapest_core()
        self.assertTrue(isinstance(cheapest_core, str) and cheapest_core != '')


class TestJob(unittest.TestCase):

    def setUp(self):
        self.client = Client(api_token=RESCALE_API_KEY)
        self.job_id = None
        self.submitted = False

    def test_1_create_job(self):
        self.job_id = self.create_job()
        self.assertTrue(isinstance(self.job_id, str) and self.job_id != '')

    def test_2_submit_job(self):
        if self.job_id is None:
            self.job_id = self.create_job()
        success = self.client.submit_job(self.job_id)
        self.submitted = success
        self.assertTrue(success)

    def test_3_get_job_status(self):
        if self.job_id is None:
            self.job_id = self.create_job()
        if not self.submitted:
            self.submitted = self.client.submit_job(self.job_id)
        if not self.submitted:
            self.fail('Job not submitted')
        else:
            statuses = self.client.get_job_status(self.job_id)
            status = statuses[-1]['status']
            self.assertTrue(status.lower() in ['pending', 'running', 'completed', 'failed'])

    def test_4_get_job_results(self):
        if self.job_id is None:
            self.job_id = self.create_job()
        if not self.submitted:
            self.submitted = self.client.submit_job(self.job_id)
        if not self.submitted:
            self.fail('Job not submitted')

        self.client.wait_for_job(self.job_id)

        with tempfile.TemporaryDirectory() as temp_dir:
            self.client.download_all_results(self.job_id, temp_dir)
            self.assertTrue(len(list(Path(temp_dir).iterdir())) > 0)

    def create_job(self):
        return self.client.create_job(
            name='Test Job',
            software_code=TEST_SOFTWARE_CODE,
            command='cd airfoil2D;./Allrun',
            input_files=TEST_INPUT_FILES,
            version=TEST_SOFTWARE_VERSION,
            project_id=TEST_PROJECT_ID,
            core_type=TEST_CORE_TYPE
        )
