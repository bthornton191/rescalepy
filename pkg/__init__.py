# ---------------------
version = '0.3.1'
commit_message = '''Add RescaleFile class and optimize common file uploads in batch processing
- Add RescaleFile class to represent uploaded files with id and name
- Add upload() method returning RescaleFile, deprecate upload_file()
- Add download() method accepting RescaleFile or str, deprecate download_file()
- Update create_job() to accept List[Union[Path, RescaleFile]] for input_files
- Update BatchRunner.common_files to accept List[Union[Path, RescaleFile]]
- Common files uploaded once and reused across all jobs in batch
- Add typing_extensions dependency for @deprecated decorator
- Add tests for RescaleFile and common file upload optimization
- Update copilot-instructions.md with string quote conventions'''

date = 'January 29th, 2026'
# ---------------------
author = 'Ben Thornton'
author_email = 'bthorn191@gmail.com'
name = 'rescalepy'
description = 'a Python client library for the Rescale API'
install_requires = ['requests', 'keyring', 'typing_extensions']
extras_require = {'batch': ['tqdm']}
