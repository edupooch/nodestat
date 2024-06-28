from setuptools import setup

setup(
    name='nodestat',
    version='0.13',
    py_modules=['nodestat'],
    entry_points={
        'console_scripts': [
            'nodestat = nodestat:main',
        ],
    },
)