# ---------------------
version = '0.1.1'
commit_message = '''Made the endpoint an instance variable so that it can be set per client. Created an `itar` boolean parameter for the client to automatically use the itar endpoint.'''
date = 'January 23rd, 2026'
# ---------------------
author = 'Ben Thornton'
author_email = 'bthorn191@gmail.com'
name = 'rescalepy'
description = 'a Python client library for the Rescale API'
install_requires = ['requests', 'keyring']
extras_require = {'batch': ['tqdm']}
