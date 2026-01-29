# ---------------------
version = '0.3.0'
commit_message = '''Add RescaleFile class and optimize common file uploads in batch processing'''
date = 'January 29th, 2026'
# ---------------------
author = 'Ben Thornton'
author_email = 'bthorn191@gmail.com'
name = 'rescalepy'
description = 'a Python client library for the Rescale API'
install_requires = ['requests', 'keyring', 'typing_extensions']
extras_require = {'batch': ['tqdm']}
