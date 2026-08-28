"""Small template showing the minimum adapter shape."""

from forgefuzz.adapters.python import PythonAdapter


class MyLanguageAdapter(PythonAdapter):
    name = "my_language"

    # Replace generate/mutate/validate/emit/observe one stage at a time.
