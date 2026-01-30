# ---------------------
version = '0.4.0'
commit_message = '''Add thread safety, download progress bar, and download_delay to BatchRunner
- Add threading.Lock for thread-safe state access during concurrent submission
- Add tqdm progress bar to download phase with leave=False
- Add download_delay parameter (default 5s) to wait for Rescale file indexing
- Fix download pattern matching to use basename instead of full path
- Add debug logging for download pattern matching
- Add 6 tests for download_delay functionality (64 tests total)'''

date = 'January 30th, 2026'
# ---------------------
author = 'Ben Thornton'
author_email = 'bthorn191@gmail.com'
name = 'rescalepy'
description = 'a Python client library for the Rescale API'
install_requires = ['requests', 'keyring', 'typing_extensions']
extras_require = {'batch': ['tqdm']}
