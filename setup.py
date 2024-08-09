import setuptools
import pkg

with open('README.md', 'r') as fid:
    long_description = fid.read()

setuptools.setup(
    name=pkg.name,
    version=pkg.version,
    author=pkg.author,
    author_email=pkg.author_email,
    description=pkg.description,
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/bthornton191/rescalepy',
    packages=setuptools.find_packages(exclude=['test',
                                               'pkg',
                                               'env',
                                               'docs',
                                               'rst',
                                               'dist',
                                               'build',
                                               'rescalepy.egg-info']),
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: Microsoft :: Windows',
    ],
    install_requires=pkg.install_requires,
)
