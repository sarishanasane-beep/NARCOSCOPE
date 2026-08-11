"""Candidate services package.

Deliberately empty: import ``app.services.candidates.service`` directly
so loading any service module never drags in the whole package and
cannot create an import cycle with the document processing pipeline.
"""
