# ---------------------
version = '0.4.1'
commit_message = '''Single job-level progress bar and logging cleanup
- Replace per-file download progress bars with single job-level bar in _monitor_phase
- Replace print() with logging module in client.py (wait_for_job, download)
- Fix tqdm fallback class to support context manager usage
- Replace deprecated download_file() calls with download()
- Rename _download_file_with_retry to _download_with_retry'''

date = 'January 30th, 2026'
# ---------------------
author = 'Ben Thornton'
author_email = 'bthorn191@gmail.com'
name = 'rescalepy'
description = 'a Python client library for the Rescale API'
install_requires = ['requests', 'keyring', 'typing_extensions']
extras_require = {'batch': ['tqdm']}
