from setuptools import setup, find_packages

setup(
    name="cell-runtime",
    version="0.1.0",
    description="The 8-primitive cell as a working Python type. The Quilt canon, not as essay but as type.",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="SuperInstance",
    license="MIT",
    py_modules=["cell_runtime"],
    package_dir={"": "src"},
    python_requires=">=3.8",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    entry_points={
        "console_scripts": [
            "cell-runtime=cell_runtime:_cli",
        ],
    },
)
