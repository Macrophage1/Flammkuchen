from setuptools import setup

APP = ['Flamecake.py']
OPTIONS = {
    'argv_emulation': True,
    'packages': ['tkinter', 'sqlite3'],
    'iconfile': 'Logo-Flamecake.icns',  # Nur wenn vorhanden
}

setup(
    app=APP,
    name='Flamecake',
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
