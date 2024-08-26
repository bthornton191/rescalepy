# rescalepy
![PyPI - Downloads](https://img.shields.io/pypi/dm/rescalepy)

This is a Python client library for the Rescale API. It provides a simple way to interact with the Rescale API from your Python applications.

## Installation

You can install the library using pip:

```bash
pip install rescalepy
```

## Usage in scripts

To use the library, you need to create a client object and authenticate with the Rescale API. You 
can then use the client object to interact with the API.

Here is an example of how to use the library to create/submit an OpenFoam job on Rescale:

```python
from rescalepy import Client

API_TOKEN = 'your-token'
client = Client(api_token=API_TOKEN)
job_id = client.create_job(
    name='OpenFoam Job',
    command='cd airfoil2D;./Allrun',
    software_code='openfoam_plus',
    input_files=['airfoil2D'], # can be files or directories
    version='v1712+-intelmpi',
    project_id='your-project-id',
    core_type='emerald_max',
)

client.submit_job(job_id)
```

Here is an example of how to use the library to get the status of a job on Rescale:

```python
statuses = client.get_job_status(job_id)
current_status = statuses[0]['status']

if current_status == 'COMPLETED':
    print('Job completed successfully')
elif current_status == 'FAILED':
    print('Job failed')
elif current_status == 'PENDING':
    print('Job is pending')
elif current_status == 'RUNNING':
    print('Job is running')
else:
    print('Job status is unknown')
```

Here is an example of how to use the library to monitor and wait for a job to complete on Rescale 
and then download the output files:

```python
client.wait_for_job(job_id)
client.download_all_results(job_id)
```

## CLI Usage

The library also provides a command line interface that you can use to interact with the Rescale 
API. You can use the CLI to create/submit jobs, monitor jobs, and download job outputs.

Here is an example of how to use the CLI to create/submit an OpenFoam job on Rescale:

```bash
python -m rescalepy submit "OpenFoam CLI Job" "airfoil2D" \
--api-token "your-token" \
--software-code "openfoam_plus" \
--command "cd airfoil2D;./Allrun" \
--version "v1712+-intelmpi" \
--project-id "your-project-id" \
--core-type "emerald_max"
```

