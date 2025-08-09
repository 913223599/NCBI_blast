from setuptools import setup, find_packages

setup(
    name="ncbi_blast_tool",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "biopython>=1.78",
        "PyQt6>=6.0.0",
        "openai>=1.0.0,<2.0.0",
        "httpx>=0.23.0,<0.28.0"
    ],
    entry_points={
        'console_scripts': [
            'ncbi_blast=src.main:main',
        ],
    },
    author="User",
    description="A tool for performing BLAST searches against NCBI database",
    python_requires='>=3.6',
)