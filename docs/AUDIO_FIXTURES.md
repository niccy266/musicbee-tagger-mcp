# Audio Test Fixtures

The small audio fixtures under test_files/test_audio_files/ remain tracked in Git.
They are required for the requires_audio_fixtures tests and are never modified by the test suite:
tests that need to write tags copy the fixture into tmp_path first.
An autouse fixture in tests/conftest.py hashes the fixtures before and after every test
and fails if any test changes them.

If a fixture ever needs to change, regenerate it deliberately, update expected ground truth
in tests/test_real_files.py, and commit the new hash.
