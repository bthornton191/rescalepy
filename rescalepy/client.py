from pathlib import Path
import shutil
import tempfile
import time
from typing import List, Union
import requests
from typing_extensions import deprecated

from .config import get_api_key

ENDPOINT = 'https://platform.rescale.com/api/v2/'
ITAR_ENDPOINT = 'https://itar.rescale.com/api/v2/'


# TODO: Figure out how to use the api to query for cores-per-slot instead of hard coding it here
CORES_PER_SLOT = {
    'onyx': 18,
    'amber': 60
}


DEFAULT_LICENSING = {
    'useRescaleLicense': False,
    'userDefinedLicenseSettings': {
        'featureSets': [],
    }
}


API_MSG = ('API token must be provided or stored using `python -m rescalepy config --api-key`.'
           'To get an API token, go to https://platform.rescale.com/user/settings/api-key/ and '
           'create a new token.')


class RescaleFile:
    """Reference to an uploaded file on Rescale.

    Parameters
    ----------
    id : str
        The Rescale file ID.
    name : str, optional
        The filename.

    """

    def __init__(self, id: str, name: str = None):
        self.id = id
        self.name = name

    def __repr__(self):
        if self.name:
            return f'RescaleFile({self.id!r}, name={self.name!r})'
        return f'RescaleFile({self.id!r})'

    def __eq__(self, other):
        if isinstance(other, RescaleFile):
            return self.id == other.id
        return False

    def __hash__(self):
        return hash(self.id)


class Client():
    def __init__(self, api_token=None, licensing=None, itar=False):
        self.api_token = api_token or get_api_key()
        self.endpoint = ITAR_ENDPOINT if itar else ENDPOINT
        self.licensing = licensing or DEFAULT_LICENSING

        if self.api_token is None or not self.validate_api_token():
            raise ValueError(API_MSG)

    def create_job(self,
                   name: str,
                   software_code: str,
                   input_files: List[Union[Path, RescaleFile]],
                   command: str,
                   version=None,
                   core_type='onyx',
                   project_id=None,
                   n_cores=1,
                   wall_time: int = 48) -> str:
        """Creates a Rescale job.

        Parameters
        ----------
        name : str
            Job Name
        software_code : str
            The code for the software/analysis to use
        input_files : List[Union[Path, RescaleFile]]
            Paths to input files or RescaleFile references to already-uploaded files
        command : str
            Command to run on rescale to start the job
        version : str, optional
            Version code indicating which version of the software to use, by default latest version
        core_type : str, optional
            Core type code indicating which type of hardware to use, by default cheapest option
        n_cores : int, optional
            Number of cores to use. , by default 1
            Note for MSC Adams Users: Must match the number of processors specified in the adm file
        wall_time : int, optional
            Wall time in hours, by default 48

        Returns
        -------
        str
            Job id

        """
        analysis = {
            'code': software_code,
            'version': version or self.get_latest_software_version(software_code)
        }

        hardware = {
            'coreType': core_type or self.get_cheapest_core(),
            'coresPerSlot': n_cores,
            'cores': n_cores,
            'walltime': wall_time
        }

        file_ids = []
        for file in input_files:
            if isinstance(file, RescaleFile):
                file_ids.append({'id': file.id})
            else:
                file_ids.append({'id': self.upload(file).id})

        licensing = {
            'useRescaleLicense': self.licensing['useRescaleLicense'],
            'userDefinedLicenseSettings': self.licensing['userDefinedLicenseSettings']
        }

        data = {
            'name': name,
            'jobanalyses': [{
                'analysis': analysis,
                'command': command,
                'hardware': hardware,
                'inputFiles': file_ids,
                **licensing
            }]
        }

        response = requests.post(
            self.endpoint + 'jobs/',
            headers={'Content-Type': 'application/json', **self.headers},
            json=data
        )

        try:
            job_id = response.json()['id']
        except KeyError:
            raise ValueError(f'Error creating job: {response.text}')

        if project_id:
            self.add_job_to_project(job_id, project_id)

        return job_id

    def add_job_to_project(self, job_id: str,  project_id: str):
        """Add a job to a project

        Parameters
        ----------
        job_id : str
            ID of the job
        org_code : str
            Organization code
        project_id : str
            ID of the project

        Returns
        -------
        bool
            True if the job was successfully added to the project

        """
        response = requests.patch(
            f'https://platform.rescale.com/api/v2/jobs/{job_id}/',
            json={'projectId': project_id},
            headers=self.headers
        )

        return response.json()['projectId'] == project_id

    def submit_job(self, job_id: str, wait=False) -> str:
        """Submits a previously created job

        Parameters
        ----------
        job_id : str
            Job id
        wait : bool, optional
            If True, wait for the job to complete and download the results files. False by default

        Returns
        -------
        bool
            True if the job was successfully submitted

        """
        response = requests.post(
            self.endpoint + f'jobs/{job_id}/submit/',
            headers={'Content-Type': 'application/json', 'Authorization': f'Token {self.api_token}'}
        )

        if wait and response.status_code == 200:
            self.wait_for_job(job_id)
            for file_dict in self.list_job_results_files(job_id):
                self.download_file(file_dict['id'], file_dict['name'])

        return response.status_code == 200

    def wait_for_job(self, job_id: str, interval=10):
        """Wait for a job to complete

        Parameters
        ----------
        job_id : str
            ID of the job
        interval : int, optional
            Time in seconds to wait between checking the job status, by default 10

        """
        prev_status = None

        while True:
            status_dict = self.get_job_status(job_id)[0]
            status: str = status_dict['status']
            status_date: str = status_dict['statusDate']

            if status != prev_status:
                print(f'{status_date} - Job {job_id}: {status}')

            if status.lower() in ['completed', 'force_stop']:
                break

            prev_status = status
            time.sleep(interval)

    def upload(self, file: Path, type_id: int = 1, zip_if_dir: bool = True) -> RescaleFile:
        """Upload a file to Rescale.

        Parameters
        ----------
        file : Path
            Local path to the file or directory to upload.
        type_id : int, optional
            File type identifier. Defaults to 1 (input file).
            1   input file
            2   template file
            3   parameter file
            4   script file
            5   output file
            7   design variable file
            8   case file
            9   optimizer file
            10  temporary file
        zip_if_dir : bool, optional
            If True and file is a directory, zip it before uploading. Defaults to True.

        Returns
        -------
        RescaleFile
            Reference to the uploaded file.

        """
        file = Path(file)
        original_name = file.name

        with tempfile.TemporaryDirectory() as tmpdir:
            if file.is_dir() and zip_if_dir:
                file = Path(shutil.make_archive(
                    Path(tmpdir) / file.stem,
                    'zip',
                    file.parent,
                    file.stem
                ))
                original_name = file.name

            response = requests.post(
                self.endpoint + 'files/contents/',
                headers=self.headers,
                files={'file': (file.name, file.open('rb'), {'type_id': type_id})}
            )

        file_id = response.json()['id']
        return RescaleFile(id=file_id, name=original_name)

    @deprecated('Use upload() instead, which returns a RescaleFile object')
    def upload_file(self, file: Path, type_id: int, zip_if_dir=True) -> str:
        """Upload a file to rescale.

        .. deprecated::
            Use :meth:`upload` instead, which returns a :class:`RescaleFile`.

        Parameters
        ----------
        file : Path
            Local path to file.
        type_id : int
            File type identifier.
        zip_if_dir : bool, optional
            If True and file is a directory, zip it before uploading.

        Returns
        -------
        str
            File id.

        """
        return self.upload(file, type_id, zip_if_dir).id

    def get_job_details(self, job_id: str) -> dict:
        response = requests.get(self.endpoint + f'jobs/{job_id}/', headers=self.headers)
        return response.json()

    def get_job_status(self, job_id: str) -> list:
        """Get the status of a job

        Note
        ----
        Statuses are datestamped and the most recent status is the first in the list

        Parameters
        ----------
        job_id : str
            ID of the job

        Returns
        -------
        list
            A list of dictionaries containing the datestamped statuses. The date is contained in the 
            'statusDate' key and the status is contained in the 'status' key. The possilbe statuses 
            are:
                - PENDING
                - QUEUED
                - STARTED
                - VALIDATED
                - EXECUTING
                - COMPLETED
                - STOPPING
                - WAITING_FOR_CLUSTER
                - FORCE_STOP
                - WAITING_FOR_QUEUE

        """
        return self.get(self.endpoint + f'jobs/{job_id}/statuses/',
                        headers={**self.headers, 'Content-Type': 'application/json'})

    def download(self, file: Union[RescaleFile, str], dst: Path) -> None:
        """Download a file from Rescale.

        Parameters
        ----------
        file : RescaleFile or str
            The file to download, either as a RescaleFile object or a file ID string.
        dst : Path
            Destination path for the downloaded file.

        """
        file_id = file.id if isinstance(file, RescaleFile) else file
        response = requests.get(self.endpoint + f'files/{file_id}/contents/', headers=self.headers)

        with Path(dst).open('wb') as fd:
            for chunk in response.iter_content():
                fd.write(chunk)

        print(f'Downloaded {dst}')

    @deprecated('Use download() instead, which accepts RescaleFile or str')
    def download_file(self, file_id: str, dst: Path) -> None:
        """Download a file from rescale.

        .. deprecated::
            Use :meth:`download` instead, which accepts :class:`RescaleFile` or str.

        Parameters
        ----------
        file_id : str
            ID of the file to download.
        dst : Path
            Destination path.

        """
        self.download(file_id, dst)

    def list_job_results_files(self, job_id: str) -> list:
        """List all files associated with a job

        Parameters
        ----------
        job_id : str
            ID of the job

        Returns
        -------
        List[Dict[str, str]]
            A list of dictionaries containing the file name and id

        """
        response = requests.get(self.endpoint + f'jobs/{job_id}/files', headers=self.headers)
        return response.json()['results']

    def list_job_results(self, job_id: str) -> list:
        """...

        Parameters
        ----------
        job_id : str
            ID of the job

        Returns
        -------
        list
            TODO

        """
        response = requests.get(self.endpoint + f'jobs/{job_id}/runs', headers=self.headers)
        return response.json()['results']

    def download_all_results(self, job_id: str, dst_dir: Path = None):
        """Download all files associated with a job

        Parameters
        ----------
        job_id : str
            ID of the job
        dst_dir : Path, optional
            Destination directory, by default cwd

        """
        for file_dict in self.list_job_results_files(job_id):

            dst = (Path(file_dict['relativePath']) if dst_dir is None
                   else Path(dst_dir) / file_dict['relativePath'])

            dst.parent.mkdir(parents=True, exist_ok=True)
            self.download_file(file_dict['id'], dst)

    def list_analyses(self):
        """
        List the types of analyses available to the user

        Returns
        -------
        List[dict]
            A list of dictionaries containing the category, name, code, and versions and other 
            information for each type of analysis available to the user

        """
        return self.get(self.endpoint + 'analyses/')

    def get_latest_software_version(self, software_code: str) -> str:
        analyses = self.list_analyses()
        software = [sw for sw in analyses if sw['code'] == software_code][0]

        return software['versions'][0]['versionCode']

    def get_core_types(self):
        return self.get(self.endpoint + 'coretypes/')

    def get_cheapest_core(self):
        core_types = self.get_core_types()
        return sorted(core_types, key=lambda ct: float(ct['price']))[0]['code']

    def get(self, url: str, headers=None) -> dict:
        """Gets all the json information at the given url handling pagination.

        Parameters
        ----------
        url : str
            URL to get information from

        Returns
        -------
        dict
            JSON information

        """
        if headers is None:
            headers = self.headers

        response = requests.get(url, headers=headers)
        json: dict = response.json()
        results: List[dict] = json['results']
        while json.get('next'):
            response = requests.get(json['next'], headers=headers)
            json = response.json()
            results.extend(json['results'])

        return results

    def validate_api_token(self):
        response = requests.get(self.endpoint, headers=self.headers)
        return response.status_code != 401

    @property
    def headers(self):
        return {'Authorization': f'Token {self.api_token}'}
