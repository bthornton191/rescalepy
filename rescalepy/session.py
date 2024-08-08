import os
from pathlib import Path
from typing import List
import requests

ENDPOINT = 'https://platform.rescale.com/api/v2/'


# TODO: Figure out how to use the api to query for cores-per-slot instead of hard coding it here
CORES_PER_SLOT = {
    'onyx': 18,
    'amber': 60
}


DEFAULT_LICENSING = {
    'useRescaleLicense': True,
    'userDefinedLicenseSettings': {
        'featureSets': [],
    }
}


class Session():
    def __init__(self, api_token, licensing=None):
        self.api_token = api_token
        self.headers = {'Authorization': f'Token {self.api_token}'}
        self.licensing = licensing or DEFAULT_LICENSING

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

    def list_analyses(self):
        """
        List the types of analyses available to the user

        Returns
        -------
        List[dict]
            A list of dictionaries containing the category, name, code, and versions and other 
            information for each type of analysis available to the user

        """
        return self.get(ENDPOINT + 'analyses/')

    def get_latest_software_version(self, software_code: str) -> str:
        analyses = self.list_analyses()
        software = [sw for sw in analyses if sw['code'] == software_code][0]

        return software['versions'][0]['versionCode']

    def get_core_types(self):
        return self.get(ENDPOINT + 'coretypes/')

    def get_cheapest_core(self):
        core_types = self.get_core_types()
        return sorted(core_types, key=lambda ct: float(ct['price']))[0]['code']

    def create_job(self,
                   name: str,
                   software_code: str,
                   input_files: List[Path],
                   command: str,
                   version=None,
                   core_type='onyx',
                   n_cores=1) -> str:
        """Creates an Adams Solver Job

        Parameters
        ----------
        name : str
            Job Name
        software_code : str
            The code for the softawre/analysis to use
        input_files : List[Path]
            Paths to the input files
        command : str
            Command to run on rescale to start the job
        version : str, optional
            version code indicating which version of Adams Solver to use, by default latest version
        core_type : str, optional
            Core type code indicating which type of hardware to use, by default cheapest option
        n_cores : int, optional
            Number of cores to use.  Must match the number of processors specified in the adm file, by default 1

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
            'cores': n_cores
        }

        file_ids = [{'id': self.upload_file(file, 1)} for file in input_files]

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
            ENDPOINT + 'jobs/',
            headers={'Content-Type': 'application/json', **self.headers},
            json=data
        )
        job_id = response.json()['id']

        return job_id

    def submit_job(self, job_id: str) -> str:
        """Submits a previously created job

        Parameters
        ----------
        job_id : str
            Job id

        Returns
        -------
        bool
            True if the job was successfully submitted

        """
        response = requests.post(
            ENDPOINT + f'jobs/{job_id}/submit/',
            headers={'Content-Type': 'application/json', 'Authorization': f'Token {self.api_token}'}
        )
        return response.status_code == 200

    def upload_file(self, file: Path, type_id: int):
        """Upload a file to rescale

        Parameters
        ----------
        filename : str
            Local name of file
        type_id : int
            1   input file
            2   template file
            3   parameter file
            4   script file
            5   output file
            7   design variable file
            8   case file
            9   optimizer file
            10  temporary file

        Returns
        -------
        str
            File id

        """
        response = requests.post(
            ENDPOINT + 'files/contents/',
            headers=self.headers,
            files={'file': (file.stem, file.open('rb'), {'type_id': type_id})}
        )
        file_id = response.json()['id']
        return file_id

    def get_job_details(self, job_id: str) -> dict:
        response = requests.get(ENDPOINT + f'jobs/{job_id}/', headers=self.headers)
        return response.json()

    def get_job_status(self, job_id: str) -> list:
        """Get the status of a job

        Parameters
        ----------
        job_id : str
            ID of the job

        Returns
        -------
        list
            TODO

        """
        response = requests.get(ENDPOINT + f'jobs/{job_id}/statuses/',
                                headers={**self.headers, 'Content-Type': 'application/json'})
        return response.json()['results']

    def download_file(self, file_id: str, dst: str):
        """Download a file from rescale

        Parameters
        ----------
        file_id : str
            ID of the file to download
        dst : str
            Destination path

        """
        response = requests.get(ENDPOINT + f'files/{file_id}/', headers=self.headers)

        with open(dst, 'wb') as fd:
            for chunk in response.iter_content():
                fd.write(chunk)

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
        response = requests.get(ENDPOINT + f'jobs/{job_id}/files', headers=self.headers)
        files = [{file['name']: file['id']} for file in response.json()['results']]
        return files

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
        response = requests.get(ENDPOINT + f'jobs/{job_id}/runs', headers=self.headers)
        return response.json()['results']
