# Copilot Instructions for rescalepy

## Project Overview
`rescalepy` is a Python client library for the Rescale HPC (High-Performance Computing) API. It provides both a programmatic `Client` class and a CLI for submitting, monitoring, and downloading cloud HPC jobs.

## Architecture

### Core Components
- [rescalepy/client.py](../rescalepy/client.py) - Main `Client` class handling all Rescale API interactions (job creation, submission, file upload/download, status monitoring)
- [rescalepy/config.py](../rescalepy/config.py) - Configuration management using `keyring` for secure API token storage and `~/.rescalepy` JSON file for defaults
- [rescalepy/batch.py](../rescalepy/batch.py) - `BatchRunner` class for concurrent batch job submission, monitoring, and selective downloading with resume support
- [rescalepy/\_\_main\_\_.py](../rescalepy/__main__.py) - CLI entry point with subcommands: `submit`, `config`, `monitor`, `download`, `batch`
- [pkg/\_\_init\_\_.py](../pkg/__init__.py) - **Version and metadata source** - update `version` and `commit_message` here before releases

### API Endpoints
The client supports two Rescale endpoints (set via `itar` parameter in `Client`):
- Standard: `https://platform.rescale.com/api/v2/`
- ITAR: `https://itar.rescale.com/api/v2/`

## Development Workflow

### Running Tests
Tests require a valid Rescale API token stored in keyring under `test_rescale` service:
```bash
python -m unittest test.test_client
```
Tests use real Rescale API calls with OpenFOAM (`openfoam_plus`) and sample [test/job/airfoil2D](../test/job/airfoil2D) input files.

### Publishing to PyPI
1. Update `version` and `commit_message` in [pkg/\_\_init\_\_.py](../pkg/__init__.py)
2. Stage changes with git
3. Run `python upload_to_pip.py` - handles build, twine upload, commit, tag, and push

### Local Development
Activate virtual environment: `env\Scripts\activate` (Windows)

## Code Patterns

### Client Method Pattern
All API methods follow this structure:
- Accept typed parameters with sensible defaults
- Use `self.headers` property for auth (`{'Authorization': f'Token {self.api_token}'}`)
- Handle pagination via `self.get()` helper for list endpoints
- Return typed results (str IDs, dicts, or lists)

### Configuration Cascade
Parameters resolve in order: explicit argument → stored config (`get_config()`) → None

### RescaleFile Class
The `RescaleFile` class represents an uploaded file on Rescale:
```python
from rescalepy.client import Client, RescaleFile

client = Client()

# Upload returns a RescaleFile
ref = client.upload(Path('model.acf'))  # RescaleFile(id='abc123', name='model.acf')

# Can be reused in create_job
client.create_job(
    name='Job 1',
    software_code='adams',
    input_files=[Path('input.acf'), ref],  # Mix of Path and RescaleFile
    command='run-adams',
)

# Download accepts RescaleFile or str
client.download(ref, Path('output/model.acf'))
```

### File Upload Convention
Directories are automatically zipped before upload (see `upload` with `zip_if_dir=True`)

## Dependencies
Minimal: `requests`, `keyring`, `typing_extensions` (see [pkg/\_\_init\_\_.py](../pkg/__init__.py) `install_requires`)

Optional: `tqdm` for batch progress bars (`pip install rescalepy[batch]`)

## Key Conventions
- Job statuses: `PENDING`, `QUEUED`, `STARTED`, `VALIDATED`, `EXECUTING`, `COMPLETED`, `STOPPING`, `WAITING_FOR_CLUSTER`, `FORCE_STOP`, `WAITING_FOR_QUEUE`
- Type hints used throughout (Python 3.6+ style with `List`, `Path`)
- Docstrings follow NumPy format with Parameters/Returns sections
- **String quotes**: Use single quotes by default. Double quotes only for:
  - Docstrings (triple double quotes)
  - Nested strings (double quotes inside, single quotes outside): `f'Value: {d["key"]}'`

## Batch Module

The `BatchRunner` class in [rescalepy/batch.py](../rescalepy/batch.py) manages large batches of jobs with:
- **Concurrent submission** via `ThreadPoolExecutor`
- **Async monitoring** that polls all active jobs in parallel
- **Selective downloading** of specific result files (by pattern) into source folders
- **Resume support** via state persistence to `./rescale.json`
- **Retry logic** with exponential backoff for API failures
- **Common file optimization** - files in `common_files` are uploaded once and reused across all jobs

### BatchRunner Usage Pattern
```python
from pathlib import Path
from rescalepy import Client
from rescalepy.batch import BatchRunner

client = Client()

# Dynamic command resolution via callable
def get_command(folder: Path) -> str:
    acf = next(folder.glob('*.acf'))
    return f'run-adams -f {acf.name}'

runner = BatchRunner(
    client=client,
    software_code='adams',
    input_files='*.acf',  # glob pattern or Callable[[Path], List[Path]]
    command=get_command,  # static str or Callable[[Path], str]
    common_files=[Path('postprocess.py')],  # optional shared files
    download_patterns=['results.json', '*.msg'],
    on_complete=lambda folder, job_id, status: print(f'{folder.name}: {status}'),
    max_workers=5,
)

folders = list(Path('jobs').glob('run_*'))
runner.run(folders)
```

### Resuming Interrupted Batches
```python
# From Python
runner = BatchRunner.resume(client=Client())
runner.resume_monitoring()

# From CLI
python -m rescalepy batch resume
python -m rescalepy batch status
```

### State File (`rescale.json`)
The batch runner persists state to `./rescale.json` containing:
- `jobs`: dict mapping folder paths to `{job_id, status, downloaded}`
- `config`: batch parameters for resume validation
- `created_at`, `updated_at` timestamps
