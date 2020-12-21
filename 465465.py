from distutils.core import setup

from Cython.Build import cythonize

setup(name='win32_act',
      ext_modules=cythonize("win32_cno.py"))
