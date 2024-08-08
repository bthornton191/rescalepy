# rescalepy

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
    software_code='openfoam_plus',
    input_files = ['airfoil2D'], # can be files or directories
    version = 'v1712+-intelmpi',
    project_id = 'your-project-id',
    core_type = 'emerald_max',
)

client.submit_job(job_id)
```

## CLI Usage

The library also provides a command line interface that you can use to interact with the Rescale 
API. You can use the CLI to create/submit jobs, monitor jobs, and download job outputs.

Here is an example of how to use the CLI to create/submit an OpenFoam job on Rescale:

```bash
python -m rescalepy submit "OpenFoam Job" "airfoil2D" \
--api-token "your-token" \
--software-code "openfoam_plus" \
--input-files "airfoil2D" \
--version "v1712+-intelmpi" \
--project-id "your-project-id" \
--core-type "emerald_max"
```

