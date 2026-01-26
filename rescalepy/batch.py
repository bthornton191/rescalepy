"""Batch job submission, monitoring, and downloading for Rescale HPC jobs.

This module provides a `BatchRunner` class for managing large batches of jobs
with concurrent submission, monitoring, and selective file downloading.
State is persisted to `./rescale.json` for resume support.
"""
import fnmatch
import json
import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from .client import Client

logger = logging.getLogger(__name__)

# Try to import tqdm for progress bars, fall back to no-op if not installed
try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, **kwargs):
        """Fallback when tqdm is not installed."""
        return iterable


STATE_FILE = Path('rescale.json')
TERMINAL_STATUSES = {'completed', 'force_stop', 'failed'}
MAX_RETRIES = 3
RETRY_BACKOFF = 2  # seconds, doubles each retry


def retry(max_attempts: int = MAX_RETRIES, backoff: float = RETRY_BACKOFF):
    """Decorate a function to retry on failure with exponential backoff.

    Parameters
    ----------
    max_attempts : int, optional
        Maximum number of attempts before giving up. Defaults to MAX_RETRIES.
    backoff : float, optional
        Initial backoff time in seconds, doubles after each failure.
        Defaults to RETRY_BACKOFF.

    Returns
    -------
    Callable
        Decorated function with retry logic.

    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    wait_time = backoff * (2 ** attempt)
                    logger.warning(f'{func.__name__} failed (attempt {attempt + 1}/{max_attempts}): {e}')
                    if attempt < max_attempts - 1:
                        time.sleep(wait_time)
            raise last_error
        return wrapper
    return decorator


class BatchRunner:
    """Manage batch submission, monitoring, and downloading of Rescale jobs.

    Parameters
    ----------
    client : Client
        Rescale API client instance.
    software_code : str
        Software/analysis code (e.g., 'adams', 'openfoam_plus').
    input_files : str or Callable[[Path], List[Path]]
        Glob pattern relative to each job folder (e.g., '*.acf') or a callable
        that takes a folder Path and returns a list of input file Paths.
    command : str or Callable[[Path], str]
        Static command string or a callable that takes a folder Path and
        returns the command string for that job.
    download_patterns : List[str]
        Filename patterns to download (fnmatch style, e.g., ['*.json', '*.msg']).
    version : str, optional
        Software version code. If None, uses latest version.
    core_type : str, optional
        Hardware core type code. Defaults to 'onyx'.
    n_cores : int, optional
        Number of cores per job. Defaults to 1.
    project_id : str, optional
        Project ID to associate jobs with.
    common_files : List[Path], optional
        Additional files to include with every job.
    on_complete : Callable[[Path, str, str], None], optional
        Callback invoked when a job completes. Receives (folder, job_id, status).
    max_workers : int, optional
        Maximum concurrent operations. Defaults to 5.
    skip_existing : bool, optional
        If True, skip downloading files that already exist locally. Defaults to False.
    poll_interval : int, optional
        Seconds between status polls during monitoring. Defaults to 30.

    Examples
    --------
    >>> from rescalepy import Client
    >>> from rescalepy.batch import BatchRunner
    >>>
    >>> client = Client()
    >>>
    >>> def get_command(folder):
    ...     acf = next(folder.glob('*.acf'))
    ...     return f'run-adams -f {acf.name}'
    >>>
    >>> runner = BatchRunner(
    ...     client=client,
    ...     software_code='adams',
    ...     input_files='*.acf',
    ...     command=get_command,
    ...     download_patterns=['results.json', '*.msg'],
    ... )
    >>>
    >>> folders = list(Path('jobs').glob('run_*'))
    >>> runner.run(folders)

    """

    def __init__(
        self,
        client: Client,
        software_code: str,
        input_files: Union[str, Callable[[Path], List[Path]]],
        command: Union[str, Callable[[Path], str]],
        download_patterns: List[str],
        version: Optional[str] = None,
        core_type: str = 'onyx',
        n_cores: int = 1,
        project_id: Optional[str] = None,
        common_files: Optional[List[Path]] = None,
        on_complete: Optional[Callable[[Path, str, str], None]] = None,
        max_workers: int = 5,
        skip_existing: bool = False,
        poll_interval: int = 30,
    ):
        self.client = client
        self.software_code = software_code
        self.version = version
        self.core_type = core_type
        self.n_cores = n_cores
        self.project_id = project_id
        self.input_files = input_files
        self.command = command
        self.common_files = common_files or []
        self.download_patterns = download_patterns
        self.on_complete = on_complete
        self.max_workers = max_workers
        self.skip_existing = skip_existing
        self.poll_interval = poll_interval

        self._state: Dict[str, Any] = {}
        self._load_state()

    def _load_state(self) -> None:
        """Load state from rescale.json if it exists.

        If the file exists but cannot be parsed, starts with empty state.
        Ensures the state dict has 'jobs' and 'created_at' keys.

        """
        if STATE_FILE.exists():
            try:
                self._state = json.loads(STATE_FILE.read_text())
                logger.info(f'Loaded state from {STATE_FILE}: {len(self._state.get("jobs", {}))} jobs')
            except json.JSONDecodeError:
                logger.warning(f'Could not parse {STATE_FILE}, starting fresh')
                self._state = {}
        else:
            self._state = {}

        # Ensure structure
        if 'jobs' not in self._state:
            self._state['jobs'] = {}
        if 'created_at' not in self._state:
            self._state['created_at'] = datetime.now().isoformat()

    def _save_state(self) -> None:
        """Persist current state to rescale.json.

        Updates the 'updated_at' timestamp and saves configuration
        parameters for potential resume operations.

        """
        self._state['updated_at'] = datetime.now().isoformat()
        self._state['config'] = {
            'software_code': self.software_code,
            'version': self.version,
            'core_type': self.core_type,
            'n_cores': self.n_cores,
            'project_id': self.project_id,
            'download_patterns': self.download_patterns,
        }
        STATE_FILE.write_text(json.dumps(self._state, indent=2))
        logger.debug(f'Saved state to {STATE_FILE}')

    def _resolve_input_files(self, folder: Path) -> List[Path]:
        """Resolve input files for a job folder.

        Parameters
        ----------
        folder : Path
            The job folder to resolve input files for.

        Returns
        -------
        List[Path]
            List of input file paths, including common files.

        """
        if callable(self.input_files):
            files = self.input_files(folder)
        else:
            files = list(folder.glob(self.input_files))

        # Append common files
        files.extend(self.common_files)
        return files

    def _resolve_command(self, folder: Path) -> str:
        """Resolve the command string for a job folder.

        Parameters
        ----------
        folder : Path
            The job folder to resolve the command for.

        Returns
        -------
        str
            The command string to execute on Rescale.

        """
        if callable(self.command):
            return self.command(folder)
        return self.command

    @retry()
    def _submit_folder(self, folder: Path) -> str:
        """Create and submit a job for a folder.

        Parameters
        ----------
        folder : Path
            The folder containing job input files.

        Returns
        -------
        str
            The job ID of the submitted job.

        Raises
        ------
        RuntimeError
            If job submission fails after retries.

        """
        folder_key = str(folder.resolve())

        # Skip if already submitted
        if folder_key in self._state['jobs']:
            existing: Dict[str, Any] = self._state['jobs'][folder_key]
            if existing.get('job_id'):
                logger.debug(f'Skipping {folder.name}: already submitted as {existing["job_id"]}')
                return existing['job_id']

        input_files = self._resolve_input_files(folder)
        command = self._resolve_command(folder)

        logger.info(f'Submitting {folder.name}: {len(input_files)} files, command={command[:50]}...')

        job_id = self.client.create_job(
            name=folder.name,
            software_code=self.software_code,
            input_files=input_files,
            command=command,
            version=self.version,
            core_type=self.core_type,
            n_cores=self.n_cores,
            project_id=self.project_id,
        )

        success = self.client.submit_job(job_id)
        if not success:
            raise RuntimeError(f'Failed to submit job {job_id}')

        self._state['jobs'][folder_key] = {
            'job_id': job_id,
            'status': 'submitted',
            'downloaded': False,
        }
        self._save_state()

        logger.info(f'Submitted {folder.name} as job {job_id}')
        return job_id

    def _get_active_jobs(self) -> Dict[str, Dict[str, Any]]:
        """Return jobs that are not in a terminal state.

        Returns
        -------
        Dict[str, Dict[str, Any]]
            Dictionary mapping folder paths to job data for all active jobs.

        """
        return {
            folder: data for folder, data in self._state['jobs'].items()
            if data.get('status', '').lower() not in TERMINAL_STATUSES
        }

    def _poll_job_status(self, folder: str, job_id: str) -> str:
        """Poll and update status for a single job.

        Parameters
        ----------
        folder : str
            The resolved folder path (used as state key).
        job_id : str
            The Rescale job ID to poll.

        Returns
        -------
        str
            The current status of the job.

        """
        try:
            statuses: List[Dict[str, Any]] = self.client.get_job_status(job_id)
            if statuses:
                status: str = statuses[0]['status'].lower()
                old_status: str = self._state['jobs'][folder].get('status', '')

                if status != old_status:
                    logger.info(f'{Path(folder).name} ({job_id}): {old_status} -> {status}')
                    self._state['jobs'][folder]['status'] = status

                return status
        except Exception as e:
            logger.error(f'Error polling {job_id}: {e}')

        return self._state['jobs'][folder].get('status', 'unknown')

    def _download_job_results(self, folder: str, job_id: str) -> None:
        """Download matching result files into the job folder.

        Parameters
        ----------
        folder : str
            The resolved folder path where files will be downloaded.
        job_id : str
            The Rescale job ID to download files from.

        """
        folder_path = Path(folder)

        if self._state['jobs'][folder].get('downloaded'):
            logger.debug(f'Skipping download for {folder_path.name}: already downloaded')
            return

        try:
            files: List[Dict[str, Any]] = self.client.list_job_results_files(job_id)
        except Exception as e:
            logger.error(f'Failed to list files for {job_id}: {e}')
            return

        for file_dict in files:
            filename: str = file_dict.get('name', '')

            # Check if filename matches any download pattern
            if not any(fnmatch.fnmatch(filename, p) for p in self.download_patterns):
                continue

            dst = folder_path / filename

            if self.skip_existing and dst.exists():
                logger.debug(f'Skipping {filename}: already exists')
                continue

            try:
                self._download_file_with_retry(file_dict['id'], dst)
            except Exception as e:
                logger.error(f'Failed to download {filename} for {job_id}: {e}')

        self._state['jobs'][folder]['downloaded'] = True
        self._save_state()

    @retry()
    def _download_file_with_retry(self, file_id: str, dst: Path) -> None:
        """Download a single file with retry logic.

        Parameters
        ----------
        file_id : str
            The Rescale file ID to download.
        dst : Path
            The destination path for the downloaded file.

        """
        self.client.download_file(file_id, dst)
        logger.info(f'Downloaded {dst}')

    def _handle_completion(self, folder: str, job_id: str, status: str) -> None:
        """Handle a job that has reached a terminal state.

        Parameters
        ----------
        folder : str
            The resolved folder path.
        job_id : str
            The Rescale job ID.
        status : str
            The terminal status of the job.

        """
        folder_path = Path(folder)

        if status == 'completed':
            self._download_job_results(folder, job_id)

        if self.on_complete:
            try:
                self.on_complete(folder_path, job_id, status)
            except Exception as e:
                logger.error(f'on_complete callback failed for {folder_path.name}: {e}')

    def run(self, folders: List[Path]) -> None:
        """Submit, monitor, and download results for a batch of job folders.

        Parameters
        ----------
        folders : List[Path]
            List of folder paths, each containing input files for one job.

        """
        logger.info(f'Starting batch run with {len(folders)} folders')

        try:
            # Phase 1: Submit jobs
            self._submit_phase(folders)

            # Phase 2: Monitor and download
            self._monitor_phase()

        except KeyboardInterrupt:
            logger.warning('Interrupted! Saving state...')
            self._save_state()
            raise

        finally:
            self._save_state()

        logger.info('Batch run complete')
        self._print_summary()

    def _submit_phase(self, folders: List[Path]) -> None:
        """Submit all jobs concurrently.

        Parameters
        ----------
        folders : List[Path]
            List of folder paths to submit as jobs.

        """
        # Filter to folders not yet submitted
        to_submit: List[Path] = []
        for folder in folders:
            folder_key = str(folder.resolve())
            if folder_key not in self._state['jobs'] or not self._state['jobs'][folder_key].get('job_id'):
                to_submit.append(folder)

        if not to_submit:
            logger.info('All jobs already submitted')
            return

        logger.info(f'Submitting {len(to_submit)} jobs...')

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures: Dict[Future, Path] = {executor.submit(self._submit_folder, f): f for f in to_submit}

            for future in tqdm(as_completed(futures), total=len(futures), desc='Submitting'):
                folder = futures[future]
                try:
                    future.result()
                except Exception as e:
                    folder_key = str(folder.resolve())
                    logger.error(f'Failed to submit {folder.name}: {e}')
                    self._state['jobs'][folder_key] = {
                        'job_id': None,
                        'status': 'failed',
                        'downloaded': False,
                        'error': str(e),
                    }
                    self._save_state()

    def _monitor_phase(self) -> None:
        """Poll active jobs until all reach terminal state, downloading on completion."""
        while True:
            active_jobs = self._get_active_jobs()

            if not active_jobs:
                logger.info('All jobs have reached terminal state')
                break

            logger.debug(f'Polling {len(active_jobs)} active jobs...')

            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures: Dict[Future, tuple] = {
                    executor.submit(self._poll_job_status, folder, data['job_id']): (folder, data['job_id'])
                    for folder, data in active_jobs.items()
                    if data.get('job_id')
                }

                for future in as_completed(futures):
                    folder, job_id = futures[future]
                    try:
                        status = future.result()
                        if status in TERMINAL_STATUSES:
                            self._handle_completion(folder, job_id, status)
                    except Exception as e:
                        logger.error(f'Error processing {job_id}: {e}')

            self._save_state()

            # Check if any active jobs remain before sleeping
            if self._get_active_jobs():
                time.sleep(self.poll_interval)

    def _print_summary(self) -> None:
        """Print a summary of the batch run.

        Logs counts for total jobs, completed, failed, and downloaded.

        """
        jobs = self._state.get('jobs', {})
        total = len(jobs)
        completed = sum(1 for j in jobs.values() if j.get('status') == 'completed')
        failed = sum(1 for j in jobs.values() if j.get('status') in ('failed', 'force_stop'))
        downloaded = sum(1 for j in jobs.values() if j.get('downloaded'))

        logger.info(f'Summary: {total} jobs, {completed} completed, {failed} failed, {downloaded} downloaded')

    @classmethod
    def resume(
        cls,
        client: Client,
        on_complete: Optional[Callable[[Path, str, str], None]] = None,
        max_workers: int = 5,
        skip_existing: bool = False,
        poll_interval: int = 30,
    ) -> 'BatchRunner':
        """Resume a batch run from existing rescale.json state.

        Parameters
        ----------
        client : Client
            Rescale API client instance.
        on_complete : Callable[[Path, str, str], None], optional
            Callback invoked when a job completes. Receives (folder, job_id, status).
        max_workers : int, optional
            Maximum concurrent operations. Defaults to 5.
        skip_existing : bool, optional
            If True, skip downloading files that already exist locally. Defaults to False.
        poll_interval : int, optional
            Seconds between status polls during monitoring. Defaults to 30.

        Returns
        -------
        BatchRunner
            A new BatchRunner instance configured from saved state.

        Raises
        ------
        FileNotFoundError
            If no state file exists at rescale.json.

        """
        if not STATE_FILE.exists():
            raise FileNotFoundError(f'No state file found at {STATE_FILE}')

        state: Dict[str, Any] = json.loads(STATE_FILE.read_text())
        config: Dict[str, Any] = state.get('config', {})

        runner = cls(
            client=client,
            software_code=config.get('software_code', ''),
            input_files=lambda f: [],  # Not needed for resume
            command='',  # Not needed for resume
            download_patterns=config.get('download_patterns', []),
            version=config.get('version'),
            core_type=config.get('core_type', 'onyx'),
            n_cores=config.get('n_cores', 1),
            project_id=config.get('project_id'),
            on_complete=on_complete,
            max_workers=max_workers,
            skip_existing=skip_existing,
            poll_interval=poll_interval,
        )

        logger.info(f'Resuming batch with {len(runner._state.get("jobs", {}))} jobs')
        return runner

    def resume_monitoring(self) -> None:
        """Resume monitoring and downloading for incomplete jobs.

        Use this after calling `BatchRunner.resume()` to continue
        processing jobs that haven't reached terminal state.

        """
        try:
            self._monitor_phase()
        except KeyboardInterrupt:
            logger.warning('Interrupted! Saving state...')
            self._save_state()
            raise
        finally:
            self._save_state()

        logger.info('Resume complete')
        self._print_summary()

    @staticmethod
    def status() -> dict:
        """Print and return the current batch status from rescale.json.

        Returns
        -------
        dict
            The current state dictionary, or empty dict if no state file exists.

        """
        if not STATE_FILE.exists():
            logger.info('No state file found')
            return {}

        state: Dict[str, Any] = json.loads(STATE_FILE.read_text())
        jobs: Dict[str, Dict[str, Any]] = state.get('jobs', {})

        # Count by status
        status_counts: Dict[str, int] = {}
        for job in jobs.values():
            s = job.get('status', 'unknown')
            status_counts[s] = status_counts.get(s, 0) + 1

        logger.info(f'Batch state from {STATE_FILE}:')
        logger.info(f'  Created: {state.get("created_at", "unknown")}')
        logger.info(f'  Updated: {state.get("updated_at", "unknown")}')
        logger.info(f'  Total jobs: {len(jobs)}')
        for status, count in sorted(status_counts.items()):
            logger.info(f'    {status}: {count}')

        downloaded = sum(1 for j in jobs.values() if j.get('downloaded'))
        logger.info(f'  Downloaded: {downloaded}')

        return state
