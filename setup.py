# -*- coding: utf-8 -*-
from setuptools import setup, find_packages

with open('requirements.txt') as f:
	install_requires = f.read().strip().split('\n')

# get version from __version__ variable in easy2way/__init__.py
from easy2way import __version__ as version

setup(
	name='easy2way',
	version=version,
	description='Make the business easy',
	author='Ninja',
	author_email='ramyasusee23@gmail.com',
	packages=find_packages(),
	zip_safe=False,
	include_package_data=True,
	install_requires=install_requires
)
