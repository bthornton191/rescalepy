"""Tests for the batch module."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from rescalepy.batch import STATE_FILE, BatchRunner, retry
from rescalepy.client import RescaleFile


class TestRescaleFile(unittest.TestCase):
    """Tests for the RescaleFile class."""

    def test_init_with_id_only(self):
        """RescaleFile can be created with just an id."""
        rf = RescaleFile(id='abc123')
        self.assertEqual(rf.id, 'abc123')
        self.assertIsNone(rf.name)

    def test_init_with_id_and_name(self):
        """RescaleFile can be created with id and name."""
        rf = RescaleFile(id='abc123', name='model.acf')
        self.assertEqual(rf.id, 'abc123')
        self.assertEqual(rf.name, 'model.acf')

    def test_repr_with_name(self):
        """repr includes name when present."""
        rf = RescaleFile(id='abc123', name='model.acf')
        self.assertEqual(repr(rf), "RescaleFile('abc123', name='model.acf')")

    def test_repr_without_name(self):
        """repr shows only id when name is None."""
        rf = RescaleFile(id='abc123')
        self.assertEqual(repr(rf), "RescaleFile('abc123')")

    def test_equality_same_id(self):
        """Two RescaleFiles with same id are equal."""
        rf1 = RescaleFile(id='abc123', name='file1.txt')
        rf2 = RescaleFile(id='abc123', name='file2.txt')
        self.assertEqual(rf1, rf2)

    def test_equality_different_id(self):
        """Two RescaleFiles with different ids are not equal."""
        rf1 = RescaleFile(id='abc123')
        rf2 = RescaleFile(id='xyz789')
        self.assertNotEqual(rf1, rf2)

    def test_equality_with_non_rescalefile(self):
        """RescaleFile is not equal to non-RescaleFile objects."""
        rf = RescaleFile(id='abc123')
        self.assertNotEqual(rf, 'abc123')
        self.assertNotEqual(rf, {'id': 'abc123'})

    def test_hash(self):
        """RescaleFile can be used in sets and dicts."""
        rf1 = RescaleFile(id='abc123')
        rf2 = RescaleFile(id='abc123')
        rf3 = RescaleFile(id='xyz789')

        s = {rf1, rf2, rf3}
        self.assertEqual(len(s), 2)


class TestRetryDecorator(unittest.TestCase):
    """Tests for the retry decorator."""

    def test_retry_succeeds_first_attempt(self):
        """Function succeeds on first attempt."""
        call_count = [0]

        @retry(max_attempts=3, backoff=0.01)
        def succeeds():
            call_count[0] += 1
            return 'success'

        result = succeeds()

        self.assertEqual(result, 'success')
        self.assertEqual(call_count[0], 1)

    def test_retry_succeeds_after_failures(self):
        """Function succeeds after initial failures."""
        attempts = [0]

        @retry(max_attempts=3, backoff=0.01)
        def fails_twice():
            attempts[0] += 1
            if attempts[0] < 3:
                raise Exception('fail')
            return 'success'

        result = fails_twice()

        self.assertEqual(result, 'success')
        self.assertEqual(attempts[0], 3)

    def test_retry_exhausted_raises(self):
        """Function raises after all retries exhausted."""
        call_count = [0]

        @retry(max_attempts=3, backoff=0.01)
        def always_fails():
            call_count[0] += 1
            raise Exception('persistent failure')

        with self.assertRaises(Exception) as ctx:
            always_fails()

        self.assertEqual(str(ctx.exception), 'persistent failure')
        self.assertEqual(call_count[0], 3)


class TestBatchRunnerInit(unittest.TestCase):
    """Tests for BatchRunner initialization."""

    def setUp(self):
        self.mock_client = MagicMock()
        self.temp_dir = tempfile.mkdtemp()
        self.original_cwd = Path.cwd()
        # Change to temp dir so state file doesn't pollute workspace
        import os
        os.chdir(self.temp_dir)

    def tearDown(self):
        import os
        os.chdir(self.original_cwd)
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_init_with_glob_pattern(self):
        """Initialize with glob pattern for input_files."""
        runner = BatchRunner(
            client=self.mock_client,
            software_code='adams',
            input_files='*.acf',
            command='run-adams',
            download_patterns=['*.json'],
        )

        self.assertEqual(runner.software_code, 'adams')
        self.assertEqual(runner.input_files, '*.acf')
        self.assertEqual(runner.command, 'run-adams')
        self.assertEqual(runner.download_patterns, ['*.json'])

    def test_init_with_callable(self):
        """Initialize with callable for input_files and command."""
        def input_fn(f): return [f / 'input.txt']
        def command_fn(f): return f'run {f.name}'

        runner = BatchRunner(
            client=self.mock_client,
            software_code='openfoam',
            input_files=input_fn,
            command=command_fn,
            download_patterns=['*.log'],
        )

        self.assertTrue(callable(runner.input_files))
        self.assertTrue(callable(runner.command))

    def test_init_defaults(self):
        """Check default parameter values."""
        runner = BatchRunner(
            client=self.mock_client,
            software_code='test',
            input_files='*',
            command='run',
            download_patterns=[],
        )

        self.assertEqual(runner.version, None)
        self.assertEqual(runner.core_type, 'onyx')
        self.assertEqual(runner.n_cores, 1)
        self.assertEqual(runner.project_id, None)
        self.assertEqual(runner.common_files, [])
        self.assertEqual(runner.on_complete, None)
        self.assertEqual(runner.max_workers, 5)
        self.assertEqual(runner.skip_existing, False)
        self.assertEqual(runner.poll_interval, 30)

    def test_init_loads_existing_state(self):
        """State file is loaded if it exists."""
        state = {
            'jobs': {'folder1': {'job_id': 'abc123', 'status': 'completed', 'downloaded': True}},
            'created_at': '2026-01-01T00:00:00',
        }
        STATE_FILE.write_text(json.dumps(state))

        runner = BatchRunner(
            client=self.mock_client,
            software_code='test',
            input_files='*',
            command='run',
            download_patterns=[],
        )

        self.assertEqual(len(runner._state['jobs']), 1)
        self.assertIn('folder1', runner._state['jobs'])


class TestInputResolution(unittest.TestCase):
    """Tests for input file and command resolution."""

    def setUp(self):
        self.mock_client = MagicMock()
        self.temp_dir = tempfile.mkdtemp()
        self.original_cwd = Path.cwd()
        import os
        os.chdir(self.temp_dir)

        # Create test folder structure
        self.job_folder = Path(self.temp_dir) / 'job1'
        self.job_folder.mkdir()
        (self.job_folder / 'model.acf').write_text('acf content')
        (self.job_folder / 'model.adm').write_text('adm content')
        (self.job_folder / 'readme.txt').write_text('readme')

    def tearDown(self):
        import os
        os.chdir(self.original_cwd)
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_resolve_input_files_glob(self):
        """Glob pattern resolves to matching files."""
        runner = BatchRunner(
            client=self.mock_client,
            software_code='adams',
            input_files='*.acf',
            command='run',
            download_patterns=[],
        )

        files = runner._resolve_input_files(self.job_folder)

        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].name, 'model.acf')

    def test_resolve_input_files_glob_multiple(self):
        """Glob pattern can match multiple files."""
        runner = BatchRunner(
            client=self.mock_client,
            software_code='adams',
            input_files='model.*',
            command='run',
            download_patterns=[],
        )

        files = runner._resolve_input_files(self.job_folder)

        self.assertEqual(len(files), 2)
        names = {f.name for f in files}
        self.assertIn('model.acf', names)
        self.assertIn('model.adm', names)

    def test_resolve_input_files_callable(self):
        """Callable is invoked with folder path."""
        def get_inputs(folder: Path):
            return [folder / 'model.acf', folder / 'model.adm']

        runner = BatchRunner(
            client=self.mock_client,
            software_code='adams',
            input_files=get_inputs,
            command='run',
            download_patterns=[],
        )

        files = runner._resolve_input_files(self.job_folder)

        self.assertEqual(len(files), 2)

    def test_resolve_input_files_with_common_files(self):
        """Common files are uploaded once and appended as RescaleFile refs."""

        common_file = Path(self.temp_dir) / 'postprocess.py'
        common_file.write_text('# postprocess script')

        # Mock upload to return a RescaleFile
        self.mock_client.upload.return_value = RescaleFile(id='common123', name='postprocess.py')

        runner = BatchRunner(
            client=self.mock_client,
            software_code='adams',
            input_files='*.acf',
            command='run',
            common_files=[common_file],
            download_patterns=[],
        )

        # Upload common files first (normally called by run())
        runner._upload_common_files()

        files = runner._resolve_input_files(self.job_folder)

        self.assertEqual(len(files), 2)
        # First file is a Path, second is a RescaleFile
        self.assertEqual(files[0].name, 'model.acf')
        self.assertIsInstance(files[1], RescaleFile)
        self.assertEqual(files[1].name, 'postprocess.py')

    def test_resolve_command_string(self):
        """Static command string is returned as-is."""
        runner = BatchRunner(
            client=self.mock_client,
            software_code='adams',
            input_files='*.acf',
            command='run-adams -f model.acf',
            download_patterns=[],
        )

        command = runner._resolve_command(self.job_folder)

        self.assertEqual(command, 'run-adams -f model.acf')

    def test_resolve_command_callable(self):
        """Callable is invoked to generate command."""
        def get_command(folder: Path):
            acf = next(folder.glob('*.acf'))
            return f'run-adams -f {acf.name}'

        runner = BatchRunner(
            client=self.mock_client,
            software_code='adams',
            input_files='*.acf',
            command=get_command,
            download_patterns=[],
        )

        command = runner._resolve_command(self.job_folder)

        self.assertEqual(command, 'run-adams -f model.acf')


class TestStateManagement(unittest.TestCase):
    """Tests for state file loading and saving."""

    def setUp(self):
        self.mock_client = MagicMock()
        self.temp_dir = tempfile.mkdtemp()
        self.original_cwd = Path.cwd()
        import os
        os.chdir(self.temp_dir)

    def tearDown(self):
        import os
        os.chdir(self.original_cwd)
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_save_state_creates_file(self):
        """Saving state creates rescale.json."""
        runner = BatchRunner(
            client=self.mock_client,
            software_code='test',
            input_files='*',
            command='run',
            download_patterns=['*.json'],
        )

        runner._state['jobs']['folder1'] = {'job_id': 'abc', 'status': 'submitted', 'downloaded': False}
        runner._save_state()

        self.assertTrue(STATE_FILE.exists())
        state = json.loads(STATE_FILE.read_text())
        self.assertIn('jobs', state)
        self.assertIn('config', state)
        self.assertIn('updated_at', state)

    def test_save_state_includes_config(self):
        """Saved state includes batch configuration."""
        runner = BatchRunner(
            client=self.mock_client,
            software_code='adams',
            input_files='*',
            command='run',
            download_patterns=['*.json', '*.msg'],
            version='2023.1',
            core_type='emerald',
            n_cores=4,
            project_id='proj123',
        )

        runner._save_state()

        state = json.loads(STATE_FILE.read_text())
        config = state['config']
        self.assertEqual(config['software_code'], 'adams')
        self.assertEqual(config['version'], '2023.1')
        self.assertEqual(config['core_type'], 'emerald')
        self.assertEqual(config['n_cores'], 4)
        self.assertEqual(config['project_id'], 'proj123')
        self.assertEqual(config['download_patterns'], ['*.json', '*.msg'])

    def test_load_state_handles_corrupt_json(self):
        """Corrupt JSON file is handled gracefully."""
        STATE_FILE.write_text('not valid json {{{')

        runner = BatchRunner(
            client=self.mock_client,
            software_code='test',
            input_files='*',
            command='run',
            download_patterns=[],
        )

        # Should start fresh instead of crashing
        self.assertEqual(runner._state['jobs'], {})

    def test_load_state_handles_missing_keys(self):
        """Missing keys in state file are initialized."""
        STATE_FILE.write_text(json.dumps({}))

        runner = BatchRunner(
            client=self.mock_client,
            software_code='test',
            input_files='*',
            command='run',
            download_patterns=[],
        )

        self.assertIn('jobs', runner._state)
        self.assertIn('created_at', runner._state)


class TestUploadCommonFiles(unittest.TestCase):
    """Tests for common file upload optimization."""

    def setUp(self):
        self.mock_client = MagicMock()
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_upload_common_files_uploads_once(self):
        """Common files are uploaded once and cached."""
        common1 = Path(self.temp_dir) / 'common1.py'
        common2 = Path(self.temp_dir) / 'common2.py'
        common1.write_text('# common 1')
        common2.write_text('# common 2')

        self.mock_client.upload.side_effect = [
            RescaleFile(id='id1', name='common1.py'),
            RescaleFile(id='id2', name='common2.py'),
        ]

        runner = BatchRunner(
            client=self.mock_client,
            software_code='adams',
            input_files='*.acf',
            command='run',
            common_files=[common1, common2],
            download_patterns=[],
        )

        runner._upload_common_files()

        self.assertEqual(self.mock_client.upload.call_count, 2)
        self.assertEqual(len(runner._common_file_refs), 2)
        self.assertEqual(runner._common_file_refs[0].id, 'id1')
        self.assertEqual(runner._common_file_refs[1].id, 'id2')

    def test_upload_common_files_skips_if_already_uploaded(self):
        """Subsequent calls to _upload_common_files are no-ops."""
        common = Path(self.temp_dir) / 'common.py'
        common.write_text('# common')

        self.mock_client.upload.return_value = RescaleFile(id='id1', name='common.py')

        runner = BatchRunner(
            client=self.mock_client,
            software_code='adams',
            input_files='*.acf',
            command='run',
            common_files=[common],
            download_patterns=[],
        )

        runner._upload_common_files()
        runner._upload_common_files()  # Second call should be no-op

        self.assertEqual(self.mock_client.upload.call_count, 1)

    def test_upload_common_files_empty_list(self):
        """No uploads when common_files is empty."""
        runner = BatchRunner(
            client=self.mock_client,
            software_code='adams',
            input_files='*.acf',
            command='run',
            common_files=[],
            download_patterns=[],
        )

        runner._upload_common_files()

        self.mock_client.upload.assert_not_called()

    def test_upload_common_files_with_rescalefile(self):
        """RescaleFile objects are used directly without uploading."""
        existing_ref = RescaleFile(id='existing123', name='already_uploaded.py')

        runner = BatchRunner(
            client=self.mock_client,
            software_code='adams',
            input_files='*.acf',
            command='run',
            common_files=[existing_ref],
            download_patterns=[],
        )

        runner._upload_common_files()

        self.mock_client.upload.assert_not_called()
        self.assertEqual(len(runner._common_file_refs), 1)
        self.assertEqual(runner._common_file_refs[0].id, 'existing123')

    def test_upload_common_files_mixed_path_and_rescalefile(self):
        """Mixed Path and RescaleFile objects are handled correctly."""
        common_path = Path(self.temp_dir) / 'to_upload.py'
        common_path.write_text('# needs upload')
        existing_ref = RescaleFile(id='existing123', name='already_uploaded.py')

        self.mock_client.upload.return_value = RescaleFile(id='new456', name='to_upload.py')

        runner = BatchRunner(
            client=self.mock_client,
            software_code='adams',
            input_files='*.acf',
            command='run',
            common_files=[common_path, existing_ref],
            download_patterns=[],
        )

        runner._upload_common_files()

        # Only the Path should be uploaded
        self.assertEqual(self.mock_client.upload.call_count, 1)
        self.assertEqual(len(runner._common_file_refs), 2)
        self.assertEqual(runner._common_file_refs[0].id, 'new456')
        self.assertEqual(runner._common_file_refs[1].id, 'existing123')


class TestSubmitPhase(unittest.TestCase):
    """Tests for job submission."""

    def setUp(self):
        self.mock_client = MagicMock()
        self.temp_dir = tempfile.mkdtemp()
        self.original_cwd = Path.cwd()
        import os
        os.chdir(self.temp_dir)

        # Create test folders
        self.folder1 = Path(self.temp_dir) / 'job1'
        self.folder2 = Path(self.temp_dir) / 'job2'
        self.folder1.mkdir()
        self.folder2.mkdir()
        (self.folder1 / 'input.txt').write_text('input1')
        (self.folder2 / 'input.txt').write_text('input2')

    def tearDown(self):
        import os
        os.chdir(self.original_cwd)
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_submit_folder_creates_and_submits_job(self):
        """Submit folder calls create_job then submit_job."""
        self.mock_client.create_job.return_value = 'job123'
        self.mock_client.submit_job.return_value = True

        runner = BatchRunner(
            client=self.mock_client,
            software_code='test',
            input_files='*.txt',
            command='run input.txt',
            download_patterns=[],
        )

        job_id = runner._submit_folder(self.folder1)

        self.assertEqual(job_id, 'job123')
        self.mock_client.create_job.assert_called_once()
        self.mock_client.submit_job.assert_called_once_with('job123')

    def test_submit_folder_uses_folder_name_as_job_name(self):
        """Job name is set to folder name."""
        self.mock_client.create_job.return_value = 'job123'
        self.mock_client.submit_job.return_value = True

        runner = BatchRunner(
            client=self.mock_client,
            software_code='test',
            input_files='*.txt',
            command='run',
            download_patterns=[],
        )

        runner._submit_folder(self.folder1)

        call_kwargs = self.mock_client.create_job.call_args[1]
        self.assertEqual(call_kwargs['name'], 'job1')

    def test_submit_folder_passes_all_parameters(self):
        """All job parameters are passed to create_job."""
        self.mock_client.create_job.return_value = 'job123'
        self.mock_client.submit_job.return_value = True

        runner = BatchRunner(
            client=self.mock_client,
            software_code='adams',
            input_files='*.txt',
            command='run-adams',
            download_patterns=[],
            version='2023.1',
            core_type='emerald',
            n_cores=8,
            project_id='proj456',
        )

        runner._submit_folder(self.folder1)

        call_kwargs = self.mock_client.create_job.call_args[1]
        self.assertEqual(call_kwargs['software_code'], 'adams')
        self.assertEqual(call_kwargs['command'], 'run-adams')
        self.assertEqual(call_kwargs['version'], '2023.1')
        self.assertEqual(call_kwargs['core_type'], 'emerald')
        self.assertEqual(call_kwargs['n_cores'], 8)
        self.assertEqual(call_kwargs['project_id'], 'proj456')

    def test_submit_folder_updates_state(self):
        """State is updated after successful submission."""
        self.mock_client.create_job.return_value = 'job123'
        self.mock_client.submit_job.return_value = True

        runner = BatchRunner(
            client=self.mock_client,
            software_code='test',
            input_files='*.txt',
            command='run',
            download_patterns=[],
        )

        runner._submit_folder(self.folder1)

        folder_key = str(self.folder1.resolve())
        self.assertIn(folder_key, runner._state['jobs'])
        job_state = runner._state['jobs'][folder_key]
        self.assertEqual(job_state['job_id'], 'job123')
        self.assertEqual(job_state['status'], 'submitted')
        self.assertEqual(job_state['downloaded'], False)

    def test_submit_folder_skips_already_submitted(self):
        """Already submitted folders are skipped."""
        self.mock_client.create_job.return_value = 'job123'
        self.mock_client.submit_job.return_value = True

        runner = BatchRunner(
            client=self.mock_client,
            software_code='test',
            input_files='*.txt',
            command='run',
            download_patterns=[],
        )

        # Pre-populate state
        folder_key = str(self.folder1.resolve())
        runner._state['jobs'][folder_key] = {
            'job_id': 'existing_job',
            'status': 'submitted',
            'downloaded': False,
        }

        job_id = runner._submit_folder(self.folder1)

        self.assertEqual(job_id, 'existing_job')
        self.mock_client.create_job.assert_not_called()

    def test_submit_folder_raises_on_submit_failure(self):
        """RuntimeError raised if submit_job returns False."""
        self.mock_client.create_job.return_value = 'job123'
        self.mock_client.submit_job.return_value = False

        runner = BatchRunner(
            client=self.mock_client,
            software_code='test',
            input_files='*.txt',
            command='run',
            download_patterns=[],
        )

        with self.assertRaises(RuntimeError):
            runner._submit_folder(self.folder1)

    def test_submit_phase_submits_all_folders(self):
        """Submit phase processes all folders."""
        self.mock_client.create_job.side_effect = ['job1', 'job2']
        self.mock_client.submit_job.return_value = True

        runner = BatchRunner(
            client=self.mock_client,
            software_code='test',
            input_files='*.txt',
            command='run',
            download_patterns=[],
            max_workers=2,
        )

        runner._submit_phase([self.folder1, self.folder2])

        self.assertEqual(self.mock_client.create_job.call_count, 2)
        self.assertEqual(len(runner._state['jobs']), 2)

    def test_submit_phase_skips_already_submitted(self):
        """Submit phase skips folders already in state."""
        self.mock_client.create_job.return_value = 'job2'
        self.mock_client.submit_job.return_value = True

        runner = BatchRunner(
            client=self.mock_client,
            software_code='test',
            input_files='*.txt',
            command='run',
            download_patterns=[],
        )

        # Pre-populate folder1
        folder1_key = str(self.folder1.resolve())
        runner._state['jobs'][folder1_key] = {
            'job_id': 'job1',
            'status': 'completed',
            'downloaded': True,
        }

        runner._submit_phase([self.folder1, self.folder2])

        # Only folder2 should be submitted
        self.assertEqual(self.mock_client.create_job.call_count, 1)


class TestMonitorPhase(unittest.TestCase):
    """Tests for job monitoring."""

    def setUp(self):
        self.mock_client = MagicMock()
        self.temp_dir = tempfile.mkdtemp()
        self.original_cwd = Path.cwd()
        import os
        os.chdir(self.temp_dir)

        self.folder1 = Path(self.temp_dir) / 'job1'
        self.folder1.mkdir()

    def tearDown(self):
        import os
        os.chdir(self.original_cwd)
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_get_active_jobs_filters_terminal_states(self):
        """Only non-terminal jobs are returned."""
        runner = BatchRunner(
            client=self.mock_client,
            software_code='test',
            input_files='*',
            command='run',
            download_patterns=[],
        )

        runner._state['jobs'] = {
            'folder1': {'job_id': 'j1', 'status': 'executing', 'downloaded': False},
            'folder2': {'job_id': 'j2', 'status': 'completed', 'downloaded': True},
            'folder3': {'job_id': 'j3', 'status': 'queued', 'downloaded': False},
            'folder4': {'job_id': 'j4', 'status': 'force_stop', 'downloaded': False},
        }

        active = runner._get_active_jobs()

        self.assertEqual(len(active), 2)
        self.assertIn('folder1', active)
        self.assertIn('folder3', active)

    def test_poll_job_status_updates_state(self):
        """Status change is recorded in state."""
        self.mock_client.get_job_status.return_value = [{'status': 'EXECUTING', 'statusDate': '2026-01-01'}]

        runner = BatchRunner(
            client=self.mock_client,
            software_code='test',
            input_files='*',
            command='run',
            download_patterns=[],
        )

        folder_key = str(self.folder1.resolve())
        runner._state['jobs'][folder_key] = {'job_id': 'job123', 'status': 'queued', 'downloaded': False}

        status = runner._poll_job_status(folder_key, 'job123')

        self.assertEqual(status, 'executing')
        self.assertEqual(runner._state['jobs'][folder_key]['status'], 'executing')

    def test_poll_job_status_handles_api_error(self):
        """API errors are logged and previous status returned."""
        self.mock_client.get_job_status.side_effect = Exception('API error')

        runner = BatchRunner(
            client=self.mock_client,
            software_code='test',
            input_files='*',
            command='run',
            download_patterns=[],
        )

        folder_key = str(self.folder1.resolve())
        runner._state['jobs'][folder_key] = {'job_id': 'job123', 'status': 'queued', 'downloaded': False}

        status = runner._poll_job_status(folder_key, 'job123')

        self.assertEqual(status, 'queued')  # Returns previous status


class TestDownloadPhase(unittest.TestCase):
    """Tests for result file downloading."""

    def setUp(self):
        self.mock_client = MagicMock()
        self.temp_dir = tempfile.mkdtemp()
        self.original_cwd = Path.cwd()
        import os
        os.chdir(self.temp_dir)

        self.folder1 = Path(self.temp_dir) / 'job1'
        self.folder1.mkdir()

    def tearDown(self):
        import os
        os.chdir(self.original_cwd)
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_download_filters_by_pattern(self):
        """Only files matching patterns are downloaded."""
        self.mock_client.list_job_results_files.return_value = [
            {'id': 'f1', 'name': 'results.json'},
            {'id': 'f2', 'name': 'output.log'},
            {'id': 'f3', 'name': 'model.msg'},
            {'id': 'f4', 'name': 'data.csv'},
        ]

        runner = BatchRunner(
            client=self.mock_client,
            software_code='test',
            input_files='*',
            command='run',
            download_patterns=['*.json', '*.msg'],
        )

        folder_key = str(self.folder1.resolve())
        runner._state['jobs'][folder_key] = {'job_id': 'job123', 'status': 'completed', 'downloaded': False}

        runner._download_job_results(folder_key, 'job123')

        # Should download results.json and model.msg
        self.assertEqual(self.mock_client.download.call_count, 2)
        downloaded_files = [c[0][1].name for c in self.mock_client.download.call_args_list]
        self.assertIn('results.json', downloaded_files)
        self.assertIn('model.msg', downloaded_files)

    def test_download_marks_downloaded_in_state(self):
        """Downloaded flag is set after successful download."""
        self.mock_client.list_job_results_files.return_value = [
            {'id': 'f1', 'name': 'results.json'},
        ]

        runner = BatchRunner(
            client=self.mock_client,
            software_code='test',
            input_files='*',
            command='run',
            download_patterns=['*.json'],
        )

        folder_key = str(self.folder1.resolve())
        runner._state['jobs'][folder_key] = {'job_id': 'job123', 'status': 'completed', 'downloaded': False}

        runner._download_job_results(folder_key, 'job123')

        self.assertTrue(runner._state['jobs'][folder_key]['downloaded'])

    def test_download_skips_already_downloaded(self):
        """Jobs marked as downloaded are skipped."""
        runner = BatchRunner(
            client=self.mock_client,
            software_code='test',
            input_files='*',
            command='run',
            download_patterns=['*.json'],
        )

        folder_key = str(self.folder1.resolve())
        runner._state['jobs'][folder_key] = {'job_id': 'job123', 'status': 'completed', 'downloaded': True}

        runner._download_job_results(folder_key, 'job123')

        self.mock_client.list_job_results_files.assert_not_called()

    def test_download_skip_existing_files(self):
        """Existing files are skipped when skip_existing=True."""
        # Create existing file
        existing_file = self.folder1 / 'results.json'
        existing_file.write_text("{'existing': true}")

        self.mock_client.list_job_results_files.return_value = [
            {'id': 'f1', 'name': 'results.json'},
            {'id': 'f2', 'name': 'new_file.json'},
        ]

        runner = BatchRunner(
            client=self.mock_client,
            software_code='test',
            input_files='*',
            command='run',
            download_patterns=['*.json'],
            skip_existing=True,
        )

        folder_key = str(self.folder1.resolve())
        runner._state['jobs'][folder_key] = {'job_id': 'job123', 'status': 'completed', 'downloaded': False}

        runner._download_job_results(folder_key, 'job123')

        # Only new_file.json should be downloaded
        self.assertEqual(self.mock_client.download.call_count, 1)
        self.assertEqual(self.mock_client.download.call_args[0][1].name, 'new_file.json')

    def test_download_overwrites_by_default(self):
        """Existing files are overwritten when skip_existing=False (default)."""
        # Create existing file
        existing_file = self.folder1 / 'results.json'
        existing_file.write_text("{'existing': true}")

        self.mock_client.list_job_results_files.return_value = [
            {'id': 'f1', 'name': 'results.json'},
        ]

        runner = BatchRunner(
            client=self.mock_client,
            software_code='test',
            input_files='*',
            command='run',
            download_patterns=['*.json'],
            skip_existing=False,
        )

        folder_key = str(self.folder1.resolve())
        runner._state['jobs'][folder_key] = {'job_id': 'job123', 'status': 'completed', 'downloaded': False}

        runner._download_job_results(folder_key, 'job123')

        # File should still be downloaded (overwritten)
        self.assertEqual(self.mock_client.download.call_count, 1)


class TestOnCompleteCallback(unittest.TestCase):
    """Tests for the on_complete callback."""

    def setUp(self):
        self.mock_client = MagicMock()
        self.temp_dir = tempfile.mkdtemp()
        self.original_cwd = Path.cwd()
        import os
        os.chdir(self.temp_dir)

        self.folder1 = Path(self.temp_dir) / 'job1'
        self.folder1.mkdir()

    def tearDown(self):
        import os
        os.chdir(self.original_cwd)
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_on_complete_called_on_completion(self):
        """Callback is invoked when job completes."""
        callback = MagicMock()
        self.mock_client.list_job_results_files.return_value = []

        runner = BatchRunner(
            client=self.mock_client,
            software_code='test',
            input_files='*',
            command='run',
            download_patterns=[],
            on_complete=callback,
        )

        folder_key = str(self.folder1.resolve())
        runner._state['jobs'][folder_key] = {'job_id': 'job123', 'status': 'completed', 'downloaded': False}

        runner._handle_completion(folder_key, 'job123', 'completed')

        callback.assert_called_once()
        call_args = callback.call_args[0]
        # Compare resolved paths to handle Windows short path name differences
        self.assertEqual(call_args[0].resolve(), self.folder1.resolve())
        self.assertEqual(call_args[1], 'job123')
        self.assertEqual(call_args[2], 'completed')

    def test_on_complete_called_on_failure(self):
        """Callback is invoked even when job fails."""
        callback = MagicMock()

        runner = BatchRunner(
            client=self.mock_client,
            software_code='test',
            input_files='*',
            command='run',
            download_patterns=[],
            on_complete=callback,
        )

        folder_key = str(self.folder1.resolve())
        runner._state['jobs'][folder_key] = {'job_id': 'job123', 'status': 'force_stop', 'downloaded': False}

        runner._handle_completion(folder_key, 'job123', 'force_stop')

        callback.assert_called_once()
        self.assertEqual(callback.call_args[0][2], 'force_stop')

    def test_on_complete_exception_does_not_crash(self):
        """Exception in callback is logged but doesn't crash."""
        callback = MagicMock(side_effect=Exception('callback error'))
        self.mock_client.list_job_results_files.return_value = []

        runner = BatchRunner(
            client=self.mock_client,
            software_code='test',
            input_files='*',
            command='run',
            download_patterns=[],
            on_complete=callback,
        )

        folder_key = str(self.folder1.resolve())
        runner._state['jobs'][folder_key] = {'job_id': 'job123', 'status': 'completed', 'downloaded': False}

        # Should not raise
        runner._handle_completion(folder_key, 'job123', 'completed')


class TestResume(unittest.TestCase):
    """Tests for resume functionality."""

    def setUp(self):
        self.mock_client = MagicMock()
        self.temp_dir = tempfile.mkdtemp()
        self.original_cwd = Path.cwd()
        import os
        os.chdir(self.temp_dir)

    def tearDown(self):
        import os
        os.chdir(self.original_cwd)
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_resume_raises_if_no_state_file(self):
        """FileNotFoundError raised if rescale.json doesn't exist."""
        with self.assertRaises(FileNotFoundError):
            BatchRunner.resume(client=self.mock_client)

    def test_resume_loads_config_from_state(self):
        """Configuration is restored from state file."""
        state = {
            'jobs': {},
            'config': {
                'software_code': 'adams',
                'version': '2023.1',
                'core_type': 'emerald',
                'n_cores': 4,
                'project_id': 'proj123',
                'download_patterns': ['*.json', '*.msg'],
            },
            'created_at': '2026-01-01T00:00:00',
        }
        STATE_FILE.write_text(json.dumps(state))

        runner = BatchRunner.resume(client=self.mock_client)

        self.assertEqual(runner.software_code, 'adams')
        self.assertEqual(runner.version, '2023.1')
        self.assertEqual(runner.core_type, 'emerald')
        self.assertEqual(runner.n_cores, 4)
        self.assertEqual(runner.project_id, 'proj123')
        self.assertEqual(runner.download_patterns, ['*.json', '*.msg'])

    def test_resume_loads_jobs_from_state(self):
        """Job state is restored from state file."""
        state = {
            'jobs': {
                'folder1': {'job_id': 'j1', 'status': 'completed', 'downloaded': True},
                'folder2': {'job_id': 'j2', 'status': 'executing', 'downloaded': False},
            },
            'config': {'software_code': 'test', 'download_patterns': []},
            'created_at': '2026-01-01T00:00:00',
        }
        STATE_FILE.write_text(json.dumps(state))

        runner = BatchRunner.resume(client=self.mock_client)

        self.assertEqual(len(runner._state['jobs']), 2)
        self.assertEqual(runner._state['jobs']['folder1']['status'], 'completed')
        self.assertEqual(runner._state['jobs']['folder2']['status'], 'executing')

    def test_resume_accepts_override_params(self):
        """Override parameters are applied."""
        state = {
            'jobs': {},
            'config': {'software_code': 'test', 'download_patterns': []},
            'created_at': '2026-01-01T00:00:00',
        }
        STATE_FILE.write_text(json.dumps(state))

        callback = MagicMock()
        runner = BatchRunner.resume(
            client=self.mock_client,
            on_complete=callback,
            max_workers=10,
            skip_existing=True,
            poll_interval=60,
        )

        self.assertEqual(runner.on_complete, callback)
        self.assertEqual(runner.max_workers, 10)
        self.assertEqual(runner.skip_existing, True)
        self.assertEqual(runner.poll_interval, 60)


class TestStatus(unittest.TestCase):
    """Tests for status reporting."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.original_cwd = Path.cwd()
        import os
        os.chdir(self.temp_dir)

    def tearDown(self):
        import os
        os.chdir(self.original_cwd)
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_status_returns_empty_if_no_file(self):
        """Empty dict returned if no state file exists."""
        result = BatchRunner.status()

        self.assertEqual(result, {})

    def test_status_returns_state(self):
        """State is returned from file."""
        state = {
            'jobs': {
                'folder1': {'job_id': 'j1', 'status': 'completed', 'downloaded': True},
                'folder2': {'job_id': 'j2', 'status': 'executing', 'downloaded': False},
                'folder3': {'job_id': 'j3', 'status': 'completed', 'downloaded': True},
            },
            'config': {'software_code': 'test'},
            'created_at': '2026-01-01T00:00:00',
            'updated_at': '2026-01-01T01:00:00',
        }
        STATE_FILE.write_text(json.dumps(state))

        result = BatchRunner.status()

        self.assertEqual(len(result['jobs']), 3)


class TestFullRun(unittest.TestCase):
    """Integration tests for the full run pipeline."""

    def setUp(self):
        self.mock_client = MagicMock()
        self.temp_dir = tempfile.mkdtemp()
        self.original_cwd = Path.cwd()
        import os
        os.chdir(self.temp_dir)

        # Create test folders
        self.folder1 = Path(self.temp_dir) / 'job1'
        self.folder2 = Path(self.temp_dir) / 'job2'
        self.folder1.mkdir()
        self.folder2.mkdir()
        (self.folder1 / 'input.txt').write_text('input1')
        (self.folder2 / 'input.txt').write_text('input2')

    def tearDown(self):
        import os
        os.chdir(self.original_cwd)
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_run_completes_immediately_finished_jobs(self):
        """Jobs that complete immediately are handled."""
        # Setup: jobs return completed on first poll
        self.mock_client.create_job.side_effect = ['job1', 'job2']
        self.mock_client.submit_job.return_value = True
        self.mock_client.get_job_status.return_value = [{'status': 'COMPLETED', 'statusDate': '2026-01-01'}]
        self.mock_client.list_job_results_files.return_value = [
            {'id': 'f1', 'name': 'results.json'}
        ]

        callback = MagicMock()
        runner = BatchRunner(
            client=self.mock_client,
            software_code='test',
            input_files='*.txt',
            command='run',
            download_patterns=['*.json'],
            on_complete=callback,
            max_workers=2,
            poll_interval=0.1,
        )

        runner.run([self.folder1, self.folder2])

        # Both jobs should be completed and downloaded
        self.assertEqual(callback.call_count, 2)
        for folder_key in runner._state['jobs']:
            self.assertEqual(runner._state['jobs'][folder_key]['status'], 'completed')
            self.assertTrue(runner._state['jobs'][folder_key]['downloaded'])

    def test_run_saves_state_on_interrupt(self):
        """State is saved when KeyboardInterrupt occurs."""
        self.mock_client.create_job.side_effect = ['job1', KeyboardInterrupt()]
        self.mock_client.submit_job.return_value = True

        runner = BatchRunner(
            client=self.mock_client,
            software_code='test',
            input_files='*.txt',
            command='run',
            download_patterns=[],
            max_workers=1,  # Sequential to control order
        )

        with self.assertRaises(KeyboardInterrupt):
            runner.run([self.folder1, self.folder2])

        # State file should exist with partial progress
        self.assertTrue(STATE_FILE.exists())


class TestPrintSummary(unittest.TestCase):
    """Tests for summary printing."""

    def setUp(self):
        self.mock_client = MagicMock()
        self.temp_dir = tempfile.mkdtemp()
        self.original_cwd = Path.cwd()
        import os
        os.chdir(self.temp_dir)

    def tearDown(self):
        import os
        os.chdir(self.original_cwd)
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_print_summary_counts_correctly(self):
        """Summary counts are correct."""
        runner = BatchRunner(
            client=self.mock_client,
            software_code='test',
            input_files='*',
            command='run',
            download_patterns=[],
        )

        runner._state['jobs'] = {
            'f1': {'job_id': 'j1', 'status': 'completed', 'downloaded': True},
            'f2': {'job_id': 'j2', 'status': 'completed', 'downloaded': True},
            'f3': {'job_id': 'j3', 'status': 'force_stop', 'downloaded': False},
            'f4': {'job_id': 'j4', 'status': 'failed', 'downloaded': False},
            'f5': {'job_id': 'j5', 'status': 'completed', 'downloaded': False},
        }

        # Should not raise
        runner._print_summary()


class TestDownloadDelay(unittest.TestCase):
    """Tests for download_delay functionality."""

    def setUp(self):
        self.mock_client = MagicMock()
        self.temp_dir = tempfile.mkdtemp()
        self.original_cwd = Path.cwd()
        import os
        os.chdir(self.temp_dir)
        self.folder1 = Path(self.temp_dir) / 'job1'
        self.folder1.mkdir()

    def tearDown(self):
        import os
        os.chdir(self.original_cwd)
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_download_delay_defaults_to_5(self):
        """download_delay defaults to 5 seconds."""
        runner = BatchRunner(
            client=self.mock_client,
            software_code='test',
            input_files='*',
            command='run',
            download_patterns=[],
        )
        self.assertEqual(runner.download_delay, 5)

    def test_download_delay_custom_value(self):
        """download_delay can be set to a custom value."""
        runner = BatchRunner(
            client=self.mock_client,
            software_code='test',
            input_files='*',
            command='run',
            download_patterns=[],
            download_delay=15,
        )
        self.assertEqual(runner.download_delay, 15)

    @patch('rescalepy.batch.time.sleep')
    def test_download_delay_applied_before_download(self, mock_sleep):
        """Delay is applied before downloading on completion."""
        self.mock_client.list_job_results_files.return_value = []

        runner = BatchRunner(
            client=self.mock_client,
            software_code='test',
            input_files='*',
            command='run',
            download_patterns=[],
            download_delay=10,
        )

        folder_key = str(self.folder1.resolve())
        runner._state['jobs'][folder_key] = {'job_id': 'job123', 'status': 'completed', 'downloaded': False}

        runner._handle_completion(folder_key, 'job123', 'completed')

        mock_sleep.assert_called_once_with(10)

    @patch('rescalepy.batch.time.sleep')
    def test_download_delay_zero_skips_sleep(self, mock_sleep):
        """download_delay=0 skips the sleep call."""
        self.mock_client.list_job_results_files.return_value = []

        runner = BatchRunner(
            client=self.mock_client,
            software_code='test',
            input_files='*',
            command='run',
            download_patterns=[],
            download_delay=0,
        )

        folder_key = str(self.folder1.resolve())
        runner._state['jobs'][folder_key] = {'job_id': 'job123', 'status': 'completed', 'downloaded': False}

        runner._handle_completion(folder_key, 'job123', 'completed')

        mock_sleep.assert_not_called()

    @patch('rescalepy.batch.time.sleep')
    def test_download_delay_not_applied_on_failure(self, mock_sleep):
        """Delay is not applied when job fails (no download needed)."""
        runner = BatchRunner(
            client=self.mock_client,
            software_code='test',
            input_files='*',
            command='run',
            download_patterns=[],
            download_delay=10,
        )

        folder_key = str(self.folder1.resolve())
        runner._state['jobs'][folder_key] = {'job_id': 'job123', 'status': 'force_stop', 'downloaded': False}

        runner._handle_completion(folder_key, 'job123', 'force_stop')

        mock_sleep.assert_not_called()

    def test_resume_passes_download_delay(self):
        """resume() passes download_delay to the runner."""
        state = {
            'jobs': {},
            'config': {
                'software_code': 'test',
                'download_patterns': ['*.txt'],
            },
            'created_at': '2026-01-30T00:00:00',
        }
        STATE_FILE.write_text(json.dumps(state))

        runner = BatchRunner.resume(
            client=self.mock_client,
            download_delay=20,
        )

        self.assertEqual(runner.download_delay, 20)


if __name__ == '__main__':
    unittest.main()
