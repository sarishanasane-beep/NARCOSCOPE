"""Document services package.

Deliberately empty: submodules (``upload``, ``processing``, ``cleaning``,
``extractors``, ``storage``, ``validation``, ``similarity``, ``segments``)
are imported directly by callers. Importing one submodule therefore never
pulls in the whole package, which prevents import cycles between document
processing and candidate persistence.
"""
